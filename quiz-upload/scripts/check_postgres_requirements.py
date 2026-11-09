"""Read-only deployment audit. Reads QUIZ_DATABASE_URL from process environment only."""
import asyncio
import json
import os
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    url=os.environ.get('QUIZ_DATABASE_URL','').strip()
    if not url.startswith('postgresql+asyncpg://'):
        raise RuntimeError('Set QUIZ_DATABASE_URL to the deployment PostgreSQL asyncpg URL; do not paste it into chat or commit it.')
    engine=create_async_engine(url)
    try:
        async with engine.connect() as conn:
            async with conn.begin():
                await conn.execute(text('set transaction read only'))
                role=(await conn.execute(text('select rolsuper,rolbypassrls from pg_roles where rolname=current_user'))).mappings().one()
                output={'mode':'read-only','server_role':dict(role),'tables':{}}
                for table in ('quiz_sets','quiz_submissions'):
                    row=(await conn.execute(text('''select c.relrowsecurity,c.relforcerowsecurity,
                        c.relowner=(select oid from pg_roles where rolname=current_user) as server_is_owner
                        from pg_class c join pg_namespace n on n.oid=c.relnamespace
                        where n.nspname='public' and c.relname=:table'''),{'table':table})).mappings().one()
                    output['tables'][table]=dict(row)
                    output['tables'][table]['client_privileges']={}
                    for client in ('anon','authenticated'):
                        output['tables'][table]['client_privileges'][client]=(await conn.execute(text('''select
                            has_table_privilege(:role,:table,'SELECT') as can_select,
                            has_table_privilege(:role,:table,'INSERT') as can_insert,
                            has_table_privilege(:role,:table,'UPDATE') as can_update,
                            has_table_privilege(:role,:table,'DELETE') as can_delete'''),{'role':client,'table':'public.'+table})).mappings().one()
                        output['tables'][table]['client_privileges'][client]=dict(output['tables'][table]['client_privileges'][client])
                output['submission_unique_constraints']=await conn.run_sync(lambda c: inspect(c).get_unique_constraints('quiz_submissions',schema='public'))
                output['sets_with_multiple_submissions']=await conn.scalar(text('select count(*) from (select quiz_set_id from public.quiz_submissions group by quiz_set_id having count(*)>1) duplicates'))
                print(json.dumps(output,ensure_ascii=False,indent=2,default=str))
    finally:
        await engine.dispose()

if __name__=='__main__':
    try: asyncio.run(main())
    except Exception:
        # Avoid echoing the URL or credentials through provider exceptions.
        print('Read-only audit failed. Check server environment, network/SSL and schema locally; no DB writes were requested.')
        raise SystemExit(1)
