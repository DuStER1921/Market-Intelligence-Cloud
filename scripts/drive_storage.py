"""Least-privilege Drive storage acceptance. No market data or secrets in output."""
import hashlib
import json
import os
import re
import time
import requests

API="https://www.googleapis.com/drive/v3"
UPLOAD="https://www.googleapis.com/upload/drive/v3/files"
TOKEN="https://oauth2.googleapis.com/token"
SCOPE="https://www.googleapis.com/auth/drive.file"
FOLDER="Market Intelligence Storage v1"
MIME_FOLDER="application/vnd.google-apps.folder"
MARKER={"mic_schema":"storage-v1"}
FIELDS="id,name,mimeType,parents,trashed,shared,ownedByMe,appProperties,size,md5Checksum"
CANARY_NAME="storage-canary-v1.json"
CANARY=b'{"schema":"mic-storage-canary-v1","synthetic":true}\n'

class StorageError(Exception):
    """Fixed safe diagnostic code only."""

def require(condition,code):
    if not condition:
        raise StorageError(code)

def valid_id(value):
    require(isinstance(value,str) and re.fullmatch(r"[A-Za-z0-9_-]{10,200}",value) is not None,"INVALID_DRIVE_ID")
    return value

def digest(data):
    return hashlib.sha256(data).hexdigest()

def oauth(session):
    try:
        config=json.loads(os.environ.get("DRIVE_OAUTH_JSON",""))
    except (ValueError,TypeError):
        raise StorageError("MISSING_OR_INVALID_OAUTH_JSON") from None
    require(isinstance(config,dict) and set(config)=={"client_id","client_secret","refresh_token"}
        and all(isinstance(v,str) and v.strip() for v in config.values()),"INVALID_OAUTH_CONFIG")
    try:
        r=session.post(TOKEN,data={**config,"grant_type":"refresh_token"},timeout=(5,20),allow_redirects=False)
    except requests.RequestException:
        raise StorageError("OAUTH_TRANSPORT_ERROR") from None
    require(r.status_code==200,"OAUTH_REFRESH_FAILED")
    b=r.json()
    require(isinstance(b,dict) and isinstance(b.get("access_token"),str) and b["access_token"],"INVALID_TOKEN_RESPONSE")
    require(isinstance(b.get("scope"),str) and set(b["scope"].split())=={SCOPE},
            "UNEXPECTED_OR_UNVERIFIED_OAUTH_SCOPE")
    require(str(b.get("token_type","")).lower()=="bearer","INVALID_TOKEN_TYPE")
    # Mask newly issued tokens before any other operation in GitHub Actions.
    if os.environ.get("GITHUB_ACTIONS")=="true":
        print("::add-mask::"+b["access_token"],flush=True)
    return b["access_token"]

class Drive:
    def __init__(self,session,token):
        self.s=session
        self.headers={"Authorization":"Bearer "+token}

    def request(self,method,url,**kwargs):
        return self.s.request(method,url,headers={**self.headers,**kwargs.pop("headers",{})},
            timeout=(5,20),allow_redirects=False,**kwargs)

    def json(self,method,url,**kwargs):
        r=self.request(method,url,**kwargs)
        if r.status_code!=200:
            raise StorageError("DRIVE_HTTP_"+str(r.status_code))
        return r.json()

    def meta(self,file_id):
        return self.json("GET",API+"/files/"+valid_id(file_id),params={"fields":FIELDS})

    def list(self,q):
        result=[]
        token=None
        seen=set()
        for _ in range(20):
            params={"q":q,"spaces":"drive","pageSize":100,"fields":"nextPageToken,files("+FIELDS+")"}
            if token:
                params["pageToken"]=token
            b=self.json("GET",API+"/files",params=params)
            require(isinstance(b.get("files"),list),"INVALID_LIST_RESPONSE")
            result.extend(b["files"])
            token=b.get("nextPageToken")
            if not token:
                return result
            require(isinstance(token,str) and token not in seen,"INVALID_PAGE_TOKEN")
            seen.add(token)
        raise StorageError("LIST_PAGE_CAP")

    def private(self,file_id):
        meta=self.meta(file_id)
        require(meta.get("ownedByMe") is True and meta.get("shared") is False
                and meta.get("trashed") is False,"NOT_PRIVATE_OWNED")
        # Verify actual permissions in addition to the shared flag.
        b=self.json("GET",API+"/files/"+valid_id(file_id)+"/permissions",
                    params={"fields":"nextPageToken,permissions(type,role)","pageSize":100})
        require(not b.get("nextPageToken") and b.get("permissions")==[{"type":"user","role":"owner"}],
                "UNEXPECTED_PERMISSIONS")
        return meta

    def new_id(self):
        b=self.json("GET",API+"/files/generateIds",params={"count":1,"space":"drive","type":"files"})
        require(isinstance(b.get("ids"),list) and len(b["ids"])==1,"INVALID_GENERATED_ID")
        return valid_id(b["ids"][0])

    def create(self,metadata,data=None):
        # A retry after a transport failure reuses the exact same Drive-generated ID.
        metadata={**metadata,"id":self.new_id()}
        file_id=metadata["id"]
        if data is None:
            url=API+"/files"
            kwargs={"json":metadata,"params":{"fields":FIELDS}}
        else:
            boundary="mic-"+digest(data)[:32]
            raw=(("--"+boundary+"\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n").encode()
                 +json.dumps(metadata,separators=(",",":")).encode()
                 +("\r\n--"+boundary+"\r\nContent-Type: application/json\r\n\r\n").encode()
                 +data+("\r\n--"+boundary+"--\r\n").encode())
            url=UPLOAD
            kwargs={"data":raw,"headers":{"Content-Type":"multipart/related; boundary="+boundary},
                    "params":{"uploadType":"multipart","fields":FIELDS}}
        for attempt in range(2):
            try:
                r=self.request("POST",url,**kwargs)
            except (requests.Timeout,requests.ConnectionError):
                if attempt:
                    raise StorageError("CREATE_OUTCOME_UNKNOWN") from None
                time.sleep(2)
                continue
            if r.status_code in (200,201,409):
                # Even conflict must be verified by ID and by the caller's exact content check.
                return self.meta(file_id)
            if r.status_code in (500,502,503,504) and not attempt:
                time.sleep(2)
                continue
            raise StorageError("CREATE_HTTP_"+str(r.status_code))
        raise StorageError("CREATE_OUTCOME_UNKNOWN")

    def bootstrap(self):
        q="trashed = false and mimeType = '"+MIME_FOLDER+"' and appProperties has { key='mic_schema' and value='storage-v1' }"
        found=self.list(q)
        require(len(found)<=1,"DUPLICATE_STORAGE_ROOT")
        meta=found[0] if found else self.create({"name":FOLDER,"mimeType":MIME_FOLDER,"appProperties":MARKER})
        root=self.private(meta["id"])
        require(root.get("name")==FOLDER and root.get("mimeType")==MIME_FOLDER
                and root.get("appProperties",{}).get("mic_schema")=="storage-v1","INVALID_STORAGE_ROOT")
        return {"status":"PASS","mode":"bootstrap","created":not found,
                "folder_name":FOLDER,"next":"Move the folder into the designated private project folder and set DRIVE_STORAGE_FOLDER_ID."}

    def verify_root(self,folder,parent):
        folder,parent=valid_id(folder),valid_id(parent)
        require(folder!=parent,"INVALID_PARENT")
        root=self.private(folder)
        require(root.get("name")==FOLDER and root.get("mimeType")==MIME_FOLDER
                and root.get("appProperties",{}).get("mic_schema")=="storage-v1","INVALID_STORAGE_ROOT")
        require(root.get("parents")==[parent],"WRONG_PROJECT_PARENT")
        return root

    def store_canary(self,folder):
        folder=valid_id(folder)
        q="'"+folder+"' in parents and trashed = false and name = '"+CANARY_NAME+"'"
        found=self.list(q)
        require(len(found)<=1,"DUPLICATE_CANARY")
        metadata={"name":CANARY_NAME,"mimeType":"application/json","parents":[folder],
                  "appProperties":{"mic_schema":"storage-v1","sha256":digest(CANARY)}}
        meta=found[0] if found else self.create(metadata,CANARY)
        verified=self.private(meta["id"])
        require(verified.get("name")==CANARY_NAME and verified.get("parents")==[folder]
                and verified.get("mimeType")=="application/json"
                and verified.get("appProperties")==metadata["appProperties"],"CANARY_METADATA_MISMATCH")
        require(str(verified.get("size"))==str(len(CANARY)),"CANARY_SIZE_MISMATCH")
        r=self.request("GET",API+"/files/"+valid_id(verified["id"]),params={"alt":"media"})
        require(r.status_code==200 and r.content==CANARY,"CANARY_CONTENT_MISMATCH")
        after=self.list(q)
        require(len(after)==1 and after[0]["id"]==verified["id"],"CANARY_IDEMPOTENCY_FAILED")
        return verified["id"],not found

    def acceptance(self,folder,parent):
        self.verify_root(folder,parent)
        first,created=self.store_canary(folder)
        second,created_again=self.store_canary(folder)
        require(first==second and not created_again,"CANARY_IDEMPOTENCY_FAILED")
        self.verify_root(folder,parent)
        return {"status":"PASS","mode":"acceptance","privacy":"PASS",
                "write":"PASS","readback":"PASS","sha256":digest(CANARY),
                "idempotency":"PASS","created":created,"duplicate_count":0,
                "synthetic_bytes":len(CANARY),"market_data_written":False,
                "production_schedule":"NOT_ENABLED"}
