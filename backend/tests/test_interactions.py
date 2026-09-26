"""Phase 3 contracts, provider isolation, crash windows and SQLite concurrency."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch
import application as app
import database as db
import interaction_service as service
import operation_store as journal
import test_stateful as base


RESULT = dict(shared_situation='Public next situation', role_a_perspective='PRIVATE A pressure', role_b_perspective='PRIVATE B pressure',
              next_decision_point='Shared decision', updated_role_a_brief='PRIVATE A evolved brief', updated_role_b_brief='PRIVATE B evolved brief',
              role_a_suggestion='PRIVATE A suggestion', role_b_suggestion='PRIVATE B suggestion')


class InteractionTests(unittest.TestCase):
    profile = base.StatefulTests.profile
    room = base.StatefulTests.room

    def setUp(self):
        base.StatefulTests.setUp(self)
        self.rid = self.room()
        self.bob, self.bauth = self.profile('Bob')
        app.join_room(self.rid, self.bob['user_id'], 'Bob')
        self.sid = app.create_scenario_session(self.rid, self.scenario)
        self.url = f'/api/v1/sessions/{self.sid}'
        self.fake = Mock()
        self.fake.validate_turn_action.return_value = {'is_valid': True, 'feedback': ''}
        self.fake.build_turn_coach_prompt.return_value = 'Turn 1 Current situation: x Your private role brief: x Reflect on what matters most to you right now'
        self.fake.generate_dynamic_ai_feedback.return_value = 'PRIVATE A Coach reply'
        self.fake.generate_next_situation_from_joint_actions.return_value = dict(RESULT)
        self.engine_patch = patch.object(service, 'engine', return_value=self.fake)
        self.engine_patch.start()
        self.addCleanup(self.engine_patch.stop)

    def action(self, auth, text='I ask to discuss our plans tonight.', turn=1):
        return self.client.post(self.url + '/turn/actions', headers=auth, json={'turn_index': turn, 'action_text': text})

    def test_llm_missing_configuration_does_not_save_coach_reply(self):
        with patch.dict(os.environ, {'ECHOROLE_AI_PROVIDER':'llm', 'ECHOROLE_LLM_API_KEY':'', 'DEEPSEEK_API_KEY':''}):
            response = self.client.post(self.url + '/coach/messages', headers=self.auth, json={'turn_index':1, 'content':'I am worried.', 'request_id':'missing-config'})
            self.assertEqual(response.status_code, 503)
            self.assertIn('ECHOROLE_LLM_API_KEY', response.text)
            self.fake.generate_dynamic_ai_feedback.assert_not_called()
            self.assertIsNone(journal.get(service.coach_key(self.sid, self.alice['user_id'], 'missing-config')))

    def test_room_languages_persist_inherit_and_use_stable_scenario_ids(self):
        from room_language import localize_scenario
        for language in ('en','zh-CN','zh-TW'):
            created = self.client.post('/api/v1/rooms', headers=self.auth, json={'request_id':'lang-'+language,'language':language})
            self.assertEqual(created.status_code, 201, created.text)
            room = created.json()
            self.assertEqual(room['language'], language)
            replay = self.client.post('/api/v1/rooms', headers=self.auth, json={'request_id':'lang-'+language,'language':'en'}).json()
            self.assertEqual(replay['language'], language)
            joined=self.client.post('/api/v1/rooms/join', headers=self.bauth,json={'invite_code':room['invite_code']}).json()
            self.assertEqual(joined['language'],language)
            catalog=self.client.get('/api/v1/scenarios',params={'language':language}).json()
            self.assertEqual(catalog[0]['id'],self.scenario['id'])
            originals=self.client.get('/api/v1/scenarios').json()
            self.assertEqual([x['id'] for x in catalog],[x['id'] for x in originals])
            if language != 'en':
                from room_language import scenario_translations
                translations=scenario_translations(language)
                self.assertEqual(set(translations),{x['id'] for x in originals})
                for translated in translations.values():
                    for field in ('category','title','context','conflict','opening_situation','role_a_brief','role_b_brief'):
                        self.assertTrue(translated[field])
            result=self.client.post(f"/api/v1/rooms/{room['id']}/sessions",headers=self.auth,json={'scenario_id':self.scenario['id']})
            self.assertEqual(result.status_code,201,result.text)
            session=result.json()
            self.assertEqual(session['title'],catalog[0]['title'])
            private=self.client.get(f"/api/v1/sessions/{session['id']}/private",headers=self.auth).json()
            self.assertEqual(private['brief'],localize_scenario(self.scenario,language)['role_a_brief'])
            self.assertEqual(self.client.patch(f"/api/v1/rooms/{room['id']}",headers=self.auth,json={'language':'en'}).status_code,405)
        self.assertEqual(self.client.post('/api/v1/rooms',headers=self.auth,json={'language':'fr'}).status_code,422)

    def test_editable_whole_stars_use_deduplication_and_latest_points(self):
        with closing(db.get_connection()) as conn:
            conn.execute('UPDATE sessions SET current_stage=3 WHERE id=?',(self.sid,))
            conn.commit()
        url=self.url+'/peer-feedback'
        first=None
        for n in range(1,6):
            body={'request_id':f'rating-{n}','peer_user_id':self.bob['user_id'],'star_rating':n,'comment':'PRIVATE comment'}
            result=self.client.post(url,headers=self.auth,json=body)
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['feedback']['score_points'],n*10)
            self.assertEqual(app.peer_score(self.bob['user_id'])['total_points'],n*10)
            self.assertEqual(self.client.post(url,headers=self.auth,json=body).status_code,200)
            if first is None:first=body
        self.client.post(url,headers=self.auth,json=first)
        self.assertEqual(app.peer_score(self.bob['user_id'])['total_points'],50)
        changed={**first,'star_rating':4}
        self.assertEqual(self.client.post(url,headers=self.auth,json=changed).status_code,409)
        self.assertEqual(self.client.post(url,headers=self.auth,json={**first,'request_id':'half','star_rating':4.5}).status_code,422)
        self.assertNotIn('PRIVATE comment',self.client.get(url,headers=self.bauth).text)
        lower={**first,'request_id':'lower','star_rating':2,'comment':'Edited private comment'}
        self.assertEqual(self.client.post(url,headers=self.auth,json=lower).status_code,200)
        self.assertEqual(app.peer_score(self.bob['user_id'])['total_points'],20)
        self.assertEqual(self.client.get(url,headers=self.auth).json()['feedback']['comment'],'Edited private comment')

    def test_ai_prompts_obey_room_language_without_rewriting_user_input(self):
        import ai_engine as ai
        for language,label in [('en','English'),('zh-CN','Simplified Chinese'),('zh-TW','Traditional Chinese')]:
            session={**self.scenario,'language':language,'current_turn':1}
            with patch.object(ai,'retrieve_relevant_notes',return_value=[]):
                bundle=ai._build_llm_coach_feedback_messages(session,'role_a','UNCHANGED USER INPUT',1,'Situation')
            self.assertIn('Room response language: '+label,bundle['messages'][0]['content'])
            self.assertIn('UNCHANGED USER INPUT',bundle['messages'][1]['content'])
            joint=ai._build_llm_joint_next_situation_messages(session,'ACTION A','ACTION B')
            self.assertIn('Room response language: '+label,joint[0]['content'])
            self.assertIn('ACTION A',joint[1]['content'])

    def seed_actions(self):
        db.save_pending_turn_action(self.sid, 1, self.alice['user_id'], 'role_a', 'A action')
        db.save_pending_turn_action(self.sid, 1, self.bob['user_id'], 'role_b', 'B action')

    def counts(self):
        with closing(db.get_connection()) as conn:
            return tuple(conn.execute(f'SELECT COUNT(*) FROM {table} WHERE session_id=?', (self.sid,)).fetchone()[0]
                         for table in ('turn_history','story_states','turn_suggestions'))

    def test_shared_chat_order_attribution_retry_and_isolation(self):
        url = f'/api/v1/rooms/{self.rid}/messages'
        first = self.client.post(url, headers=self.auth, json={'content':'First', 'request_id':'one'})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()['user_id'], self.alice['user_id'])
        self.assertEqual(self.client.post(url, headers=self.auth, json={'content':'First', 'request_id':'one'}).json(), first.json())
        self.assertEqual(self.client.post(url, headers=self.auth, json={'content':'Changed', 'request_id':'one'}).status_code, 409)
        self.client.post(url, headers=self.bauth, json={'content':'Second', 'request_id':'two'})
        db.add_ai_message(self.sid, 1, self.alice['user_id'], 'role_a', 'ai', 'SECRET COACH')
        messages = self.client.get(url, headers=self.auth)
        self.assertEqual([m['content'] for m in messages.json()], ['First','Second'])
        self.assertNotIn('SECRET COACH', messages.text)
        self.assertEqual(self.client.post(url, headers=self.auth, json={'content':'Spoof','request_id':'x','user_id':self.bob['user_id']}).status_code, 422)
        _, outsider = self.profile('Outsider')
        self.assertEqual(self.client.get(url, headers=outsider).status_code, 403)

    def test_private_authorization_and_coach_retries(self):
        own = self.client.get(self.url + '/private', headers=self.auth)
        self.assertEqual(own.json()['brief'], self.scenario['role_a_brief'])
        self.assertNotIn(self.scenario['role_b_brief'], own.text)
        self.assertEqual(self.client.get(self.url+'/roles/role_b/private', headers=self.auth).status_code,403)
        _, outsider = self.profile('Outsider')
        body = {'content':'I feel uncertain', 'turn_index':1, 'request_id':'coach1'}
        self.assertEqual(self.client.post(self.url+'/coach/messages', headers=outsider, json=body).status_code,403)
        first = self.client.post(self.url+'/coach/messages', headers=self.auth, json=body)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()['state'],'completed')
        self.assertEqual(self.client.post(self.url+'/coach/messages', headers=self.auth,json=body).json(),first.json())
        self.assertEqual(self.fake.generate_dynamic_ai_feedback.call_count,1)
        own_history=self.client.get(self.url+'/coach/messages',headers=self.auth).json()
        self.assertEqual([m['sender'] for m in own_history],['user','ai'])
        self.assertEqual(self.client.get(self.url+'/coach/messages',headers=self.bauth).json(),[])
        self.assertEqual(self.client.get(self.url+'/coach/requests/coach1',headers=self.bauth).status_code,404)
        for path in ('/private','/coach/messages','/suggestion','/turn/status','/progression'):
            self.assertEqual(self.client.get(self.url+path).status_code,401)
            self.assertEqual(self.client.get(self.url+path,headers=outsider).status_code,403)

    def test_wait_completion_once_and_private_projections(self):
        self.assertEqual(self.client.get(self.url+'/turn',headers=self.auth).json()['state'],'action_required')
        first=self.action(self.auth)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()['state'],'waiting_for_other')
        self.assertEqual(self.action(self.auth).json(),first.json())
        self.assertEqual(self.action(self.auth,'Replace my action').status_code,409)
        self.assertEqual(self.fake.generate_next_situation_from_joint_actions.call_count,0)
        second=self.action(self.bauth,'I agree to discuss the plan tonight.')
        self.assertEqual(second.status_code,200,second.text)
        self.assertEqual(second.json()['state'],'advanced')
        self.assertEqual(second.json()['current_turn'],2)
        self.assertEqual(self.counts(),(1,1,2))
        self.assertEqual(self.action(self.bauth,'I agree to discuss the plan tonight.').json(),second.json())
        self.assertEqual(self.action(self.bauth,'A different stale action').status_code,409)
        self.assertEqual(self.fake.generate_next_situation_from_joint_actions.call_count,1)
        self.assertEqual(self.client.get(self.url+'/suggestion',headers=self.auth).json()['text'],RESULT['role_a_suggestion'])
        private=self.client.get(self.url+'/private',headers=self.auth).json()
        self.assertEqual(private['brief'],RESULT['updated_role_a_brief'])
        self.assertEqual(private['pressure'],RESULT['role_a_perspective'])
        for endpoint in (self.url+'/turn/status',self.url+'/progression',f'/api/v1/rooms/{self.rid}/session',f'/api/v1/rooms/{self.rid}/messages'):
            response=self.client.get(endpoint,headers=self.auth)
            self.assertEqual(response.status_code,200)
            self.assertNotIn('PRIVATE',response.text)
            self.assertNotIn('role_b_action',response.text)
        history=self.client.get(self.url+'/progression',headers=self.auth).json()
        self.assertEqual(history[0]['resulting_situation'],RESULT['shared_situation'])

    def test_invalid_and_unauthorized_actions(self):
        _, outsider=self.profile('Outsider')
        self.assertEqual(self.action(outsider).status_code,403)
        self.assertEqual(self.action(self.auth,turn=99).status_code,409)
        self.assertEqual(self.client.post(self.url+'/turn/actions',headers=self.auth,json={'turn_index':1,'action_text':'x','user_id':self.bob['user_id']}).status_code,422)
        self.fake.validate_turn_action.return_value={'is_valid':False,'feedback':'Concrete action required'}
        self.assertEqual(self.action(self.auth).status_code,422)
        self.assertEqual(db.get_pending_turn_actions(self.sid,1),[])

    def test_competing_callers_generate_and_advance_once(self):
        self.seed_actions()
        entered, release=threading.Event(), threading.Event()
        def generate(**kwargs):
            entered.set()
            self.assertTrue(release.wait(10))
            return dict(RESULT)
        self.fake.generate_next_situation_from_joint_actions.side_effect=generate
        with ThreadPoolExecutor(max_workers=6) as pool:
            first=pool.submit(service.advance_turn,self.sid,self.alice['user_id'],1)
            self.assertTrue(entered.wait(5))
            competitors=list(pool.map(lambda _:service.advance_turn(self.sid,self.bob['user_id'],1),range(6)))
            self.assertTrue(all(r['state']=='generating' for r in competitors))
            self.assertEqual(self.fake.generate_next_situation_from_joint_actions.call_count,1)
            release.set()
            self.assertEqual(first.result()['state'],'advanced')
        self.assertEqual(self.counts(),(1,1,2))

    def test_uncertain_failure_requires_explicit_fenced_recovery(self):
        self.seed_actions()
        self.fake.generate_next_situation_from_joint_actions.side_effect=TimeoutError('provider outcome unknown')
        failed=service.advance_turn(self.sid,self.alice['user_id'],1)
        self.assertEqual(failed['state'],'uncertain')
        self.assertEqual(self.counts(),(0,0,0))
        service.advance_turn(self.sid,self.bob['user_id'],1)
        self.assertEqual(self.fake.generate_next_situation_from_joint_actions.call_count,1)
        response=self.client.post(self.url+'/turn/recover',headers=self.auth,json={'turn_index':1,'attempt_id':failed['attempt_id'],'acknowledge_uncertain':False})
        self.assertEqual(response.status_code,422)
        self.fake.generate_next_situation_from_joint_actions.side_effect=None
        recovered=self.client.post(self.url+'/turn/recover',headers=self.auth,json={'turn_index':1,'attempt_id':failed['attempt_id'],'acknowledge_uncertain':True})
        self.assertEqual(recovered.json()['state'],'advanced',recovered.text)
        self.assertEqual(self.fake.generate_next_situation_from_joint_actions.call_count,2)
        self.assertEqual(self.counts(),(1,1,2))
        self.assertEqual(self.client.post(self.url+'/turn/recover',headers=self.auth,json={'turn_index':1,'attempt_id':failed['attempt_id'],'acknowledge_uncertain':True}).status_code,409)

    def test_expired_claim_and_late_worker_fencing(self):
        self.seed_actions()
        old,_=service._claim_turn(self.sid,self.alice['user_id'],1)
        key=old['operation_key']
        with db.transaction():
            db.get_connection().execute('UPDATE operation_journal SET started_at=? WHERE operation_key=?',(time.time()-journal.CLAIM_SECONDS-1,key))
        self.assertEqual(service.turn_status(self.sid,self.alice['user_id'])['state'],'uncertain')
        service.advance_turn(self.sid,self.alice['user_id'],1)
        self.fake.generate_next_situation_from_joint_actions.assert_not_called()
        with db.transaction():
            newer=journal.recover(key,old['attempt_id'])
            self.assertFalse(journal.publish(key,old['attempt_id'],dict(RESULT)))
            self.assertTrue(journal.publish(key,newer['attempt_id'],dict(RESULT)))
        service.advance_turn(self.sid,self.alice['user_id'],1)
        self.assertEqual(self.counts(),(1,1,2))
        self.fake.generate_next_situation_from_joint_actions.assert_not_called()

    def test_saved_result_survives_persistence_failure_without_regeneration(self):
        self.seed_actions()
        with patch.object(db,'add_ai_message',side_effect=RuntimeError('after turn writes, before commit')):
            with self.assertRaises(RuntimeError):
                service.advance_turn(self.sid,self.alice['user_id'],1)
        self.assertEqual(self.counts(),(0,0,0))
        self.assertEqual(db.get_session_by_id(self.sid)['current_turn'],1)
        self.assertEqual(journal.get(service.turn_key(self.sid,1))['state'],'ready')
        result=service.advance_turn(self.sid,self.bob['user_id'],1)
        self.assertEqual(result['state'],'advanced')
        self.assertEqual(self.fake.generate_next_situation_from_joint_actions.call_count,1)
        self.assertEqual(self.counts(),(1,1,2))

    def test_coach_uncertain_recovery_and_request_conflict(self):
        self.fake.generate_dynamic_ai_feedback.side_effect=TimeoutError()
        failed=service.send_coach(self.sid,self.alice['user_id'],1,'Reflection','same')
        self.assertEqual(failed['state'],'uncertain')
        service.send_coach(self.sid,self.alice['user_id'],1,'Reflection','same')
        with self.assertRaises(app.ApplicationError):
            service.send_coach(self.sid,self.alice['user_id'],1,'Another','new')
        with self.assertRaises(app.ApplicationError):
            service.send_coach(self.sid,self.alice['user_id'],1,'Changed','same')
        self.assertEqual(self.fake.generate_dynamic_ai_feedback.call_count,1)
        self.fake.generate_dynamic_ai_feedback.side_effect=None
        recovered=service.recover_coach(self.sid,self.alice['user_id'],'same',failed['attempt_id'],True)
        self.assertEqual(recovered['state'],'completed')
        self.assertEqual([m['sender'] for m in service.coach_messages(self.sid,self.alice['user_id'])],['user','ai'])

    def test_separate_process_claims_execute_provider_once(self):
        self.seed_actions()
        counter=str(Path(self.path).with_name('provider_calls.txt'))
        code='''import types,time,os
import interaction_service as s
from pathlib import Path
def generate(**kwargs):
 with open(os.environ['CALL_COUNTER'],'a') as f: f.write('call\\n')
 time.sleep(.2)
 return {'shared_situation':'One process result'}
s.engine=lambda:types.SimpleNamespace(generate_next_situation_from_joint_actions=generate)
s.advance_turn(int(os.environ['SESSION_ID']),os.environ['PARTICIPANT'],1)
'''
        env={**os.environ,'ECHOROLE_DB_PATH':self.path,'SESSION_ID':str(self.sid),'PARTICIPANT':self.alice['user_id'],'CALL_COUNTER':counter}
        def run(_):
            subprocess.run([sys.executable,'-c',code],env=env,check=True,capture_output=True)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(run,range(4)))
        self.assertEqual(Path(counter).read_text().splitlines(),['call'])
        self.assertEqual(self.counts(),(1,1,2))

    def test_legacy_generating_actions_are_not_silently_retried(self):
        self.seed_actions()
        with db.transaction():
            db.get_connection().execute("UPDATE pending_turn_actions SET status='generating' WHERE session_id=?",(self.sid,))
        result=service.advance_turn(self.sid,self.alice['user_id'],1)
        self.assertEqual(result['state'],'uncertain')
        self.fake.generate_next_situation_from_joint_actions.assert_not_called()

    def test_swallowed_transport_timeout_is_still_uncertain(self):
        from provider_boundary import mark_uncertain
        self.seed_actions()
        def fallback(**kwargs):
            mark_uncertain()
            return dict(RESULT)
        self.fake.generate_next_situation_from_joint_actions.side_effect=fallback
        result=service.advance_turn(self.sid,self.alice['user_id'],1)
        self.assertEqual(result['state'],'uncertain')
        self.assertEqual(self.counts(),(0,0,0))

    def test_coach_requests_are_discoverable_only_by_owner(self):
        self.fake.generate_dynamic_ai_feedback.side_effect=TimeoutError()
        failed=service.send_coach(self.sid,self.alice['user_id'],1,'Reflection','findme')
        own=self.client.get(self.url+'/coach/requests',headers=self.auth)
        self.assertEqual(own.status_code,200,own.text)
        self.assertEqual(own.json(),[failed])
        self.assertEqual(self.client.get(self.url+'/coach/requests',headers=self.bauth).json(),[])

    def test_existing_database_upgrade_is_additive(self):
        source=subprocess.check_output(['git','show','460c149b3ed834ec641fef65f9790f0140ec0d6c:database.py'],text=True,encoding='utf-8')
        namespace={'__name__':'old_database'}
        exec(compile(source,'<legacy>','exec'),namespace)
        path=str(Path(self.path).with_name('legacy.db'))
        namespace['DB_NAME']=path
        namespace['init_db']()
        rid=namespace['create_room']('LEGACY')
        namespace['save_user_profile']('legacy-user','Legacy name','INFJ','Original priorities')
        namespace['add_member']('legacy-user',rid,'Legacy name')
        with closing(db.sqlite3.connect(path)) as conn:
            before=conn.execute('SELECT * FROM user_profiles').fetchall()
        with patch.object(db,'DB_NAME',path):
            app.initialize()
            app.initialize()
            with closing(db.get_connection()) as conn:
                self.assertEqual([tuple(r) for r in conn.execute('SELECT * FROM user_profiles')],before)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM operation_journal').fetchone()[0],0)
            self.assertEqual(db.get_members_by_room(rid)[0][0],'legacy-user')
            self.assertEqual(db.get_room_language(rid), 'en')

    def test_real_transport_observer_records_timeout_and_remains_request_local(self):
        # Inspect the real transport method in a separate process to preserve the
        # side-effect-free import checks in the main backend test process.
        code='''from unittest.mock import Mock, patch
import ai_engine
from provider_boundary import observe
provider=ai_engine.DeepSeekOpenAICompatibleProvider(None,None)
connection=Mock()
connection.request.side_effect=TimeoutError('simulated loss')
with patch.object(ai_engine.http.client,'HTTPSConnection',return_value=connection):
 with observe() as outcome:
  try: provider._perform_chat_completion_request('https://example.invalid/test',b'{}',{},1)
  except TimeoutError: pass
  assert outcome['uncertain']
 with observe() as fresh: assert not fresh['uncertain']
'''
        subprocess.run([sys.executable,'-c',code],check=True,capture_output=True)

    def test_coach_saved_reply_can_be_completed_without_provider_retry(self):
        service.ensure_coach_prompt(self.sid,self.alice['user_id'])
        original=db.add_ai_message
        def fail_reply(*args, **kwargs):
            sender=kwargs.get('sender',args[4] if len(args)>4 else None)
            if sender=='ai':
                raise RuntimeError('simulated reply persistence failure')
            return original(*args,**kwargs)
        with patch.object(db,'add_ai_message',side_effect=fail_reply):
            with self.assertRaises(RuntimeError):
                service.send_coach(self.sid,self.alice['user_id'],1,'Reflection','saved')
        self.assertEqual(service.coach_request(self.sid,self.alice['user_id'],'saved')['state'],'ready')
        response=self.client.post(self.url+'/coach/requests/saved/complete',headers=self.auth)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['state'],'completed')
        self.assertEqual(self.fake.generate_dynamic_ai_feedback.call_count,1)
        self.assertEqual(len(service.coach_messages(self.sid,self.alice['user_id'])),2)
