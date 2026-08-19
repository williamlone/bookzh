rem copyfile 复制文件
xcopy "d:\Website\blog\book" "d:\gae\book" /s/e/y/d
d:
cd d:\gae\book

rem clean 清理无用目录
rd zb_system\ADMIN /S/Q
rd zb_system\DEFEND /S/Q
rd zb_system\FUNCTION /S/Q
rd zb_system\IMAGE /S/Q
rd zb_system\XML-RPC /S/Q
rd zb_users\AVATAR /S/Q
rd zb_users\CACHE /S/Q
rd zb_users\DATA /S/Q
rd zb_users\EMOTION /S/Q
rd zb_users\INCLUDE /S/Q
rd zb_users\LANGUAGE /S/Q
rd zb_users\UPLOAD /S/Q
rd zb_users\THEME\default /S/Q
del *.asp /S/Q
copy page\index.html .

rem fnr 文件关键字替换
D:\Website\software\fnr.exe --cl --dir "D:\gae\book" --fileMask "*.html, *.xml" --includeSubDirectories --skipBinaryFileDetection --find "https://www.williamlong.info/book/" --replace "https://www.bookzh.com/"
D:\Website\software\fnr.exe --cl --dir "D:\gae\book" --fileMask "*.html, *.xml" --includeSubDirectories --skipBinaryFileDetection --find """www.williamlong.info""" --replace """www.bookzh.com"""
D:\Website\software\fnr.exe --cl --dir "D:\gae\book" --fileMask "*.html, *.xml" --includeSubDirectories --skipBinaryFileDetection --find "<script src=""https://www.bookzh.com/zb_system/function/c_html_js_add.asp"" type=""text/javascript""></script>" --replace "<style type=""text/css"">.comment-reply-link{display:none}.divContorPanel{display:none}.respond{display:none}</style>"
D:\Website\software\fnr.exe --cl --dir "D:\gae\book" --fileMask "*.html, *.xml" --includeSubDirectories --skipBinaryFileDetection --find "<h4>控制面板</h4>" --replace "<style type=""text/css"">.divContorPanel{display:none}</style>"

rem deploy 发布
call cmd /c gcloud config set project bookzh
call cmd /c gcloud app deploy -q