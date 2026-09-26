"use client";
import {useEffect,useRef} from 'react';
import type {SharedMessage} from '@/lib/contracts';
import {useI18n,useT} from '@/i18n/context';
import styles from './social.module.css';
export default function SharedChat({userId,messages,value,onChange,onSend,busy,disabled}:{userId:string;messages:SharedMessage[];value:string;onChange:(value:string)=>void;onSend:()=>void;busy:boolean;disabled?:boolean}) {
 const t=useT(), {language}=useI18n(); const scroll=useRef<HTMLDivElement>(null), nearBottom=useRef(true);
 const last=messages.at(-1)?.id;
 useEffect(()=>{const el=scroll.current;if(el&&nearBottom.current)el.scrollTop=el.scrollHeight;},[last]);
 return <section className={styles.chat}><h2>{t('Shared chat — visible to the room')}</h2><p>{t('Visible to everyone in this room.')}</p>
 <div ref={scroll} className={styles.history} role="region" aria-label={t('Shared room messages')} tabIndex={0} onScroll={()=>{const el=scroll.current!;nearBottom.current=el.scrollHeight-el.scrollTop-el.clientHeight<72;}}>
 {!messages.length&&<p data-empty>{t('No shared messages yet. Start a conversation with your partner.')}</p>}
 <ol>{messages.map(m=><li key={m.id} className={m.user_id===userId?styles.own:styles.other} data-message-owner={m.user_id===userId?'own':'other'}><span className={styles.avatar} aria-hidden="true">{(m.username||'?').slice(0,1).toUpperCase()}</span><div><div className={styles.meta}><strong>{m.username||t('Participant')}</strong><time dateTime={m.created_at}>{new Intl.DateTimeFormat(language,{hour:'2-digit',minute:'2-digit'}).format(new Date(m.created_at.includes('T')?m.created_at:m.created_at.replace(' ','T')+'Z'))}</time></div><p className={styles.bubble}>{m.content}</p></div></li>)}</ol></div>
 <form onSubmit={e=>{e.preventDefault();nearBottom.current=true;onSend();}}><label>{t('Shared message')}<textarea aria-label={t('Shared message')} value={value} onChange={e=>onChange(e.target.value)} required onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();if(!busy&&!disabled&&value.trim())e.currentTarget.form?.requestSubmit();}}}/></label><p className={styles.hint}>{t('Enter to send · Shift+Enter for a new line')}</p><button disabled={busy||disabled||!value.trim()}>{t(busy?'Sending…':'Send message')}</button></form></section>;
}
