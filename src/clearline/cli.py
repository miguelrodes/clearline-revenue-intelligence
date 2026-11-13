import argparse
import asyncio
import json
from .agent import MissingCredentials, verify_model
from .config import Settings
from .store import Store
from .worker import run
from .prospects import seed_prospects


def main():
    parser = argparse.ArgumentParser(description="Clearline local revenue operations")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    scan = sub.add_parser("scan")
    scan.add_argument("--analysis-limit",type=int,default=-1)
    worker = sub.add_parser("worker")
    worker.add_argument("--once",action="store_true")
    schedule = sub.add_parser("schedule")
    schedule.add_argument("--seconds",type=int,default=86400)
    schedule.add_argument("--disable",action="store_true")
    schedule.add_argument("--analysis-limit",type=int,default=-1)
    retry = sub.add_parser("retry")
    retry.add_argument("job_id")
    sub.add_parser("status")
    sub.add_parser("assess-portfolio")
    sub.add_parser("verify-api")
    prospect = sub.add_parser("prospects")
    prospect.add_argument("--research-first",action="store_true",help="Queue only the first curated public lead")
    args = parser.parse_args()
    settings = Settings.load()
    store = Store(settings.db_path)
    if args.command == "init": print(f"Initialized {settings.db_path}")
    elif args.command == "scan": print(store.enqueue("scan",{"analysis_limit":args.analysis_limit}))
    elif args.command == "worker": run(settings,args.once)
    elif args.command == "schedule":
        store.schedule(args.seconds,not args.disable,args.analysis_limit)
        print("Schedule saved; the separate worker must be running.")
    elif args.command == "retry": store.retry(args.job_id)
    elif args.command == "prospects":
        ids = seed_prospects(store,settings.as_of)
        print(json.dumps({"prospect_ids":ids,"job_id":store.queue_prospect(ids[0]) if args.research_first else None},indent=2))
    elif args.command == "assess-portfolio":
        from .operations import start_batch
        print(start_batch(store))
    elif args.command == "status":
        print(json.dumps({"jobs":store.rows("SELECT id,kind,status,error FROM jobs ORDER BY created_at DESC LIMIT 10"),
                          "opportunities":store.rows("SELECT COUNT(*) AS count FROM opportunities WHERE active=1")},indent=2))
    elif args.command == "verify-api":
        try:
            result = asyncio.run(verify_model(settings))
        except MissingCredentials as exc: parser.exit(2,str(exc)+"\n")
        except Exception as exc: parser.exit(2,f"API verification failed ({type(exc).__name__}); check project access and billing.\n")
        else:
            print(json.dumps(result,indent=2))
            if not result["available"]: parser.exit(2,"Choose an available OPENAI_MODEL before running agents.\n")


if __name__ == "__main__": main()
