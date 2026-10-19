import unittest
import requests
from uuid import uuid4

class UploadTests(unittest.TestCase):
    def test_reject_pdf(self):    #接收文件类型不是 .txt 和.md  后缀不合法编码合法
         response=requests.post(
          "http://127.0.0.1:8001/api/upload",
         files={
            "file":("test.pdf",b"test content","application/pdf")
         },
        timeout=10,    
        )

         self.assertEqual(response.status_code,400) 
         self.assertEqual(
            response.json()["detail"],
            "只支持 .txt 和 .md 文件",
        )

    def  test_reject_invalid_encoding(self):    #后缀合法编码不合法
        response=requests.post(
            "http://127.0.0.1:8001/api/upload",
            files={
                    "file":("invalid.txt",b"\xff\xfe","text/plain")
             },
            timeout=10,    
        )
        
        self.assertEqual(response.status_code,400) 
        self.assertEqual(
            response.json()["detail"],
            "文件必须是 UTF-8 编码",
        )

    def test_upload_and_reject_duplicate(self):    #上传重复文件
        filename=f"api_test_{uuid4().hex}.md"
        url="http://127.0.0.1:8001/api/upload"
        files={
            "file":(filename,b"# Test document","text/markdown")
        }

        # 第一次上传，应该成功
        response=requests.post(url,files=files,timeout=10)
        self.assertEqual(response.status_code,200,response.text)
        
        try:
            self.assertEqual(response.json()["filename"], filename)

            # 再上传同名文件，应该被拒绝
            duplicate = requests.post(url, files=files, timeout=10)
            self.assertEqual(duplicate.status_code, 409)  #同名上传
            self.assertEqual(
                duplicate.json()["detail"],
                "同名文件已存在，请先删除旧文件再上传",
            )
        finally:
            # 清理本次测试上传的文件
            deleted = requests.delete(
                f"http://127.0.0.1:8001/api/files/{filename}",
                timeout=30,
            )
            self.assertEqual(deleted.status_code, 200, deleted.text)

        # 删除后，文件列表里不应该再有这个文件
        response = requests.get(
            "http://127.0.0.1:8001/api/files",
            timeout=10,
        )
        self.assertEqual(response.status_code, 200)
        
        filenames = [item["name"] for item in response.json()]
        self.assertNotIn(filename, filenames)  #filename要查找的那个文件名  filenames当前所有文件名组成的列表
    def test_delete_missing_file(self):  #删除不存在的文件 ，应返回404
            filename = f"missing_{uuid4().hex}.md"

            response = requests.delete(
                f"http://127.0.0.1:8001/api/files/{filename}",
                timeout=10,
            )

            self.assertEqual(response.status_code, 404)
            self.assertEqual(
                response.json()["detail"],
                "文件不存在",
            )