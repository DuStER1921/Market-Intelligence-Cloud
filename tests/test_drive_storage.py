"""Synthetic tests; no Google account, network or market data."""
import json
import os
import unittest
from unittest.mock import Mock, patch
import requests
from scripts import drive_storage as d

ROOT="rootABC12345"
PARENT="parentABC12345"
FILE="fileABC12345"

def root(**kwargs):
    return {"id":ROOT,"name":d.FOLDER,"mimeType":d.MIME_FOLDER,
            "parents":[PARENT],"trashed":False,"shared":False,"ownedByMe":True,
            "appProperties":d.MARKER,**kwargs}

def canary(**kwargs):
    return {"id":FILE,"name":d.CANARY_NAME,"mimeType":"application/json",
            "parents":[ROOT],"trashed":False,"shared":False,"ownedByMe":True,
            "appProperties":{"mic_schema":"storage-v1","sha256":d.digest(d.CANARY)},
            "size":str(len(d.CANARY)),**kwargs}

class DriveTests(unittest.TestCase):
    def setUp(self):
        self.session=Mock()
        self.drive=d.Drive(self.session,"synthetic-token")
    def test_invalid_id(self):
        for invalid in (None,"root","../injection","abc' or true"):
            with self.assertRaises(d.StorageError): d.valid_id(invalid)
    def test_oauth_missing_config_no_request(self):
        with patch.dict(os.environ,{"DRIVE_OAUTH_JSON":""}):
            with self.assertRaises(d.StorageError): d.oauth(self.session)
        self.session.post.assert_not_called()
    def test_oauth_rejects_broad_scope(self):
        cfg={"client_id":"id","client_secret":"secret","refresh_token":"refresh"}
        self.session.post.return_value=Mock(status_code=200)
        self.session.post.return_value.json.return_value={"access_token":"abc","token_type":"Bearer","scope":"https://www.googleapis.com/auth/drive"}
        with patch.dict(os.environ,{"DRIVE_OAUTH_JSON":json.dumps(cfg),"GITHUB_ACTIONS":"false"}):
            with self.assertRaisesRegex(d.StorageError,"UNEXPECTED_OAUTH_SCOPE"): d.oauth(self.session)
    def test_privacy_rejects_shared_folder(self):
        with patch.object(self.drive,"meta",return_value=root(shared=True)):
            with self.assertRaisesRegex(d.StorageError,"NOT_PRIVATE_OWNED"): self.drive.private(ROOT)
    def test_privacy_rejects_extra_permission(self):
        with patch.object(self.drive,"meta",return_value=root()),patch.object(self.drive,"json",return_value={"permissions":[{"type":"user","role":"owner"},{"type":"anyone","role":"reader"}]}):
            with self.assertRaisesRegex(d.StorageError,"UNEXPECTED_PERMISSIONS"): self.drive.private(ROOT)
    def test_wrong_parent(self):
        with patch.object(self.drive,"private",return_value=root(parents=["otherABC12345"])):
            with self.assertRaisesRegex(d.StorageError,"WRONG_PROJECT_PARENT"): self.drive.verify_root(ROOT,PARENT)
    def test_bootstrap_reuses_root(self):
        with patch.object(self.drive,"list",return_value=[root()]),patch.object(self.drive,"private",return_value=root()),patch.object(self.drive,"create") as create:
            self.assertFalse(self.drive.bootstrap()["created"])
            create.assert_not_called()
    def test_duplicate_canary_blocks_write(self):
        with patch.object(self.drive,"list",return_value=[canary(),canary()]),patch.object(self.drive,"create") as create:
            with self.assertRaisesRegex(d.StorageError,"DUPLICATE_CANARY"): self.drive.store_canary(ROOT)
            create.assert_not_called()
    def test_existing_canary_verifies_without_write(self):
        with patch.object(self.drive,"list",return_value=[canary()]),patch.object(self.drive,"private",return_value=canary()),patch.object(self.drive,"request",return_value=Mock(status_code=200,content=d.CANARY)),patch.object(self.drive,"create") as create:
            self.assertEqual(self.drive.store_canary(ROOT),(FILE,False))
            create.assert_not_called()
    def test_corrupt_canary_fails(self):
        with patch.object(self.drive,"list",return_value=[canary()]),patch.object(self.drive,"private",return_value=canary()),patch.object(self.drive,"request",return_value=Mock(status_code=200,content=b"corrupt")):
            with self.assertRaisesRegex(d.StorageError,"CANARY_CONTENT_MISMATCH"): self.drive.store_canary(ROOT)
    def test_create_retry_same_generated_id(self):
        with patch.object(self.drive,"new_id",return_value=FILE) as gen,patch.object(self.drive,"request",side_effect=[requests.Timeout(),Mock(status_code=409)]) as send,patch.object(self.drive,"meta",return_value=canary()),patch.object(d.time,"sleep"):
            self.assertEqual(self.drive.create({"name":d.CANARY_NAME},d.CANARY)["id"],FILE)
            gen.assert_called_once()
            self.assertEqual(send.call_args_list[0],send.call_args_list[1])
    def test_acceptance_same_id_twice(self):
        with patch.object(self.drive,"verify_root"),patch.object(self.drive,"store_canary",side_effect=[(FILE,True),(FILE,False)]):
            report=self.drive.acceptance(ROOT,PARENT)
            self.assertEqual(report["status"],"PASS")
            self.assertEqual(report["duplicate_count"],0)
            self.assertFalse(report["market_data_written"])
    def test_acceptance_rejects_different_id(self):
        with patch.object(self.drive,"verify_root"),patch.object(self.drive,"store_canary",side_effect=[(FILE,True),("different12345",False)]):
            with self.assertRaisesRegex(d.StorageError,"CANARY_IDEMPOTENCY_FAILED"): self.drive.acceptance(ROOT,PARENT)

if __name__=="__main__":
    unittest.main()
