# EchoRole Migration Checkpoints

1. Git
- Work only on `migration/nextjs-fastapi`
- Do not merge or push unless explicitly requested
- Preserve unrelated local changes

2. Local skill
- `.agents/skills/ui-ux-pro-max/` stays local only
- Never stage, commit, or push it

3. Legacy behavior
- Existing Streamlit app remains runnable during migration
- Preserve existing AI, RAG, database, scenario, room, role and turn behavior unless explicitly approved

4. Architecture
- Next.js frontend → FastAPI → reusable existing Python logic
- FastAPI must not import `app.py`
- Do not duplicate business logic in frontend or API routes

5. Privacy
- Keep public, room-shared and private role/AI data clearly separated
- Never expose another participant's private role brief or private AI Coach content

6. Scope
- Do only the requested migration phase
- No deployment, database migration, framework upgrades or unrelated redesign unless explicitly requested

7. Verification
- Run relevant backend tests
- Verify Next.js build/typecheck when frontend is touched
- Verify Streamlit still runs when shared logic is changed
- Check `git status` before finishing
- Report anything not actually verified