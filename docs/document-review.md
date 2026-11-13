# 驗證紀錄

## 已實作範圍

`herdr_pane.py` 提供本機目前 session 與已啟用遠端的 agent 清單、同次選單選號、連線前 profile／terminal 核對、SSH 直接終端連線，以及 `--add-remote` 原生設定引導、`--remove-remote` 選號確認移除。只有正式指令 `herdr-pane`，不建立舊名稱。

## 自動測試

```sh
python3 -m unittest discover -s tests -v
```

目前 67 項測試通過，涵蓋：

- 本機／遠端合併、停用 profile、來源失敗隔離、同名與同 pane 識別碼。
- 設定變更、agent 消失或 terminal ID 被替換時拒絕連線。
- 無效 JSON、查詢逾時、取消與子程序清理；包含脫離程序群組但仍持有輸出描述符的子程序，修正前重現超時後仍等待 4 秒，修正後在期限內返回。
- SSH 位置驗證、參數傳遞、顯示控制字元清理。
- 程序祖先身分核對，不採用 UI 焦點或繼承 pane ID。
- 選單快照、非法編號、失敗後返回選單且不自動重試。
- 新增遠端委派原生命令並重新取得清單，以及空清單與全部來源失敗的結束碼。

- 遠端移除：停用／格式不支援的 profile、指定 ID、取消、設定改變、原生失敗、移除後結果核對、非互動拒絕與參數互斥。

移除流程以虛構 profile 與原生 CLI 邊界替身驗證；沒有為測試刪除使用者的真實連線。

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
- 0.2.1 已修正：重複 profile ID 全部排除、PID 必須為正整數、深層 JSON 回報查詢錯誤而非 traceback。
- 移除確認前就顯示啟用狀態；新增／移除中斷提示先查清單，互動子程序有清理寬限並恢復終端設定。
- 遠端腳本改為單行，加入 csh／tcsh 相容測試；Unicode 換行分隔符、非 UTF-8 輸入與輸出編碼均有回歸案例。
- 程序 ID 重疊的遠端會追加短暫程序標記核對，阻擋普通 Herdr 環境的 SSH 自接。核對使用 `ps -ww` 避免窄終端截斷；不改寫 profile，不建立存取權。
- 逾時測試改為等測試子程序就緒後計時，不改變正式程式的查詢期限。
- IPv6 使用 OpenSSH 可解析的 `ssh://user@[address]` 格式；拒絕無 scheme 的方括號形式。
- 新增遠端前明示：不存在的 session 會被建立並啟動。

## 文件與機敏檢查

- 初始文件發布曾進行兩方覆核、兩輪全文／SVG 結構檢查與 Gitleaks 8.30.1 工作目錄及 Git 歷史掃描，未發現機敏資料。
- 本次程式與測試工作目錄的第一輪 Gitleaks 掃描未發現憑證。
- 發布前另核對修正後全部檔案、實際 commit、作者欄位與交付 bundle；上傳後核對遠端 tree。檢查紀錄不能代替這些發布步驟。
- 四張 SVG 附 Mermaid 原稿；修改過的圖表會重新產生並檢視。SVG 不使用 foreignObject、外部圖片或 script。

公開版本另補齊安裝／更新／移除、疑難排解、與原生功能的比較及 MIT 授權。內部實作計畫已從最新版移除，但歷史仍在審查範圍。效率說明只列省去的手動步驟，沒有宣稱經過操作計時；原生多機能力與本工具的操作捷徑分別說明。

工具來源：[Gitleaks 8.30.1 官方 release](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1)。工具使用前已核對官方 checksum。

## 尚未驗證的環境與限制

- 正式 staging；Linux、新帳號與其他 Herdr 版本組合。
- 真實新帳號的密碼／MFA／首次 host-key 引導與安裝／替換 server 問題；程式保留原生互動，不自動作答。
- SSH 靜默斷線時擁有權的釋放時間，以及所有巢狀鍵盤協定。tmux、screen、zellij 與 SSH／mosh 回接等會切斷祖先關係的用法，不在本版自我辨識支援範圍。
- 細分授權、強制唯讀與全域輸入鎖不屬本工具提供的功能。

任何掃描都有範圍限制；「未發現」不代表保證不存在所有可能的機敏資料。

## 2026-11-13 再驗證

新增的 `tests/test_cli_integration.py` 會啟動真正的 Python CLI、子程序與 PTY，以虛構的 Herdr／SSH 執行檔保存測試設定；不是只呼叫函式替身。`tests/test_loopback_guard.py` 驗證程序核對、完整程序命令比對、錯誤分支及清理。這些測試不讀寫使用者的真實連線設定。

已重新驗證 macOS、Herdr 0.9.5：以隔離 session 執行啟動器本體、選號接上、輸入回顯、占用拒絕、正常 detach、SIGINT 退出與終端還原、自我辨識；另清除繼承的 session／socket 環境後查詢 default，核對 process-info 的 PID 型別。測試結束後只清理本次建立的 session。

完整測試包含正常與失敗結果；不把虛構 CLI 的結果當成真實 SSH 驗證、MFA、安裝或更新 server 的實測。

獨立審查補測：Python 3.9 與 3.13 各 41 個 CLI／PTY 情境，以及各 14 個移除情境；7 種 shell 的連線腳本與同機防護全部符合預期。曾在 Python 3.12／3.13 發現 JSON 測試的巢狀深度未超過該版本限制，已提高測試深度，不改正式程式。原先偶發的子程序啟動計時案例另連跑 30 次通過。

本機重跑曾在系統 load average 約 156 時遇到測試期限及 `ps` 期限失敗；保留此失敗紀錄，不放寬正式程式的核對期限。系統過載時可能暫時拒絕連線，應待負載降低後重試。

最終測試程式於另一台 macOS 的 Python 3.9、3.12、3.13 各跑完整 67 項均通過；本機重新執行也為 67／67。真實遠端補驗包括原生 profile 的程序查詢、啟動器選號後遇到占用回選單，以及本機 Herdr 0.9.5 環境透過 SSH 接上遠端 Herdr 0.9.1 的專用 session：帶程序標記探測、輸入回顯、detach exit 0、終端恢復、標記程序回收、遠端 agent／server 保持執行。占用測試與可寫入測試使用不同目標，不接管既有連線。
