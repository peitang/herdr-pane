# 驗證紀錄

## 已實作範圍

`herdr_pane.py` 提供本機目前 session 與已啟用遠端的 agent 清單、同次選單選號、連線前 profile／terminal 核對、SSH 直接終端連線，以及 `--add-remote` 原生設定引導。只有正式指令 `herdr-pane`，不建立舊名稱。

## 自動測試

```sh
python3 -m unittest discover -s tests -v
```

目前 29 項測試通過，涵蓋：

- 本機／遠端合併、停用 profile、來源失敗隔離、同名與同 pane 識別碼。
- 設定變更、agent 消失或 terminal ID 被替換時拒絕連線。
- 無效 JSON、查詢逾時、取消與子程序清理；包含脫離程序群組但仍持有輸出描述符的子程序，修正前重現超時後仍等待 4 秒，修正後在期限內返回。
- SSH 位置驗證、參數傳遞、顯示控制字元清理。
- 程序祖先身分核對，不採用 UI 焦點或繼承 pane ID。
- 選單快照、非法編號、失敗後返回選單且不自動重試。
- 新增遠端委派原生命令並重新取得清單，以及空清單與全部來源失敗的結束碼。

這些測試不會連接真實主機；外部 CLI 邊界使用虛構資料，逾時測試使用測試自己建立的子程序。

## 本機受控驗證

- macOS、Python 3.9、Herdr client／local server 0.9.5。
- 遠端 Herdr server 0.9.1；可在同一份清單看到本機與遠端 agent。
- 實際互動終端：非法編號可重新輸入、Enter 取消可正常退出。
- 以程式產生的 SSH 命令接上 reviewer 新建的專用測試終端，確認文字輸入／回顯，分開送出 Ctrl+B 與 Q 後正常 exit 0。
- 沒有在既有 agent 中輸入指令，也沒有替換或重啟既有 server。

## 獨立 reviewer 的隔離驗證

第二位 reviewer 使用自己建立的測試 session 驗證 Herdr 0.9.1：

- Named session 的 terminal attach 可接上；正常 detach 回傳 0。
- 第二個 writable direct attach 被拒絕，回傳 1；程式不傳 takeover。
- API 操作仍能輸入，證明 direct attach 擁有者不是全域輸入鎖。
- 同 session 的不同 pane 可以互相 attach；原生工具不拒絕接自己，因此程式另做身分核對。
- 對未執行 session 的查詢不啟動 server；直接 attach 可能留下未執行的 session 目錄，因此遠端腳本在 attach 前先查詢。
- 被其他 client takeover 後，測試中的舊 attach 不一定立即返回；程式不搶回，必要時由使用者 detach。

測試 session 已由建立者清理；沒有修改既有連線設定。

## 審查修正

- 已修正持有 pipe 的脫離子程序造成逾時／取消延後：查詢改用匿名暫存檔，等待與回收均設期限，無保留的 debug log。
- 只顯示白名單內的原生錯誤碼，不顯示完整錯誤內容。
- IPv6 使用 OpenSSH 可解析的 `ssh://user@[address]` 格式；拒絕無 scheme 的方括號形式。
- 新增遠端前明示：不存在的 session 會被建立並啟動。

## 文件與機敏檢查

- 初始文件發布曾進行兩方覆核、兩輪全文／SVG 結構檢查與 Gitleaks 8.30.1 工作目錄及 Git 歷史掃描，未發現機敏資料。
- 本次程式與測試工作目錄的第一輪 Gitleaks 掃描未發現憑證。
- 發布前另核對修正後全部檔案、實際 commit、作者欄位與交付 bundle；上傳後核對遠端 tree。檢查紀錄不能代替這些發布步驟。
- 四張 SVG 附 Mermaid 原稿；修改過的圖表會重新產生並檢視。SVG 不使用 foreignObject、外部圖片或 script。

工具來源：[Gitleaks 8.30.1 官方 release](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1)。工具使用前已核對官方 checksum。

## 尚未驗證的環境與限制

- 正式 staging；Linux、新帳號與其他 Herdr 版本組合。
- 真實新帳號的密碼／MFA／首次 host-key 引導與安裝／替換 server 問題；程式保留原生互動，不自動作答。
- SSH 靜默斷線時擁有權的釋放時間、所有巢狀鍵盤協定，以及經 tmux 等中介切斷程序祖先的 self detection。
- 細分授權、強制唯讀與全域輸入鎖不屬本工具提供的功能。

任何掃描都有範圍限制；「未發現」不代表保證不存在所有可能的機敏資料。
