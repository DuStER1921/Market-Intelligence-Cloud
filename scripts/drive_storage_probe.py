"""Manual storage qualification entrypoint; only safe status codes printed."""
import argparse
import json
import os
import re
import requests
from scripts.drive_storage import Drive, StorageError, oauth

def main():
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=("bootstrap","acceptance"))
    args=p.parse_args()
    try:
        with requests.Session() as s:
            drive=Drive(s,oauth(s))
            if args.mode=="bootstrap":
                report=drive.bootstrap()
            else:
                report=drive.acceptance(os.environ.get("DRIVE_STORAGE_FOLDER_ID"),
                                        os.environ.get("DRIVE_PROJECT_FOLDER_ID"))
    except Exception as exc:
        code=str(exc) if isinstance(exc,StorageError) and re.fullmatch(r"[A-Z0-9_]{1,80}",str(exc)) else "UNEXPECTED_STORAGE_ERROR"
        report={"status":"FAIL","mode":args.mode,"reason":code,
                "market_data_written":False,"production_schedule":"NOT_ENABLED"}
    print(json.dumps(report,indent=2))
    return 0 if report["status"]=="PASS" else 1

if __name__=="__main__":
    raise SystemExit(main())
