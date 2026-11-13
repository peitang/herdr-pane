# 疑難排解

先用 `herdr-pane --list` 看來源與提示。以下指令中的 `PROFILE_ID` 請換成 `herdr machine list --json` 的真實 id；主機與 session 範例均為虛構。

## 找不到 herdr-pane 或 Herdr

- `herdr-pane: command not found`：先執行 `~/.local/bin/herdr-pane --version`，確認安裝位置及 PATH；zsh 可執行 `rehash` 更新指令快取。
- Python 版本不足：使用 Python 3.9 以上的 `python3`。
- 工具提示找不到 Herdr：先確認 `herdr --version` 可執行；程式會查 PATH 與 `~/.local/bin/herdr`，不自動安裝 Herdr。

## 查詢失敗或逾時

```sh
herdr status server
herdr machine list --json
herdr machine status PROFILE_ID --json
```

`server_not_running` 代表目標 session 的 server 未執行。請確認要用的 session；一般列表不會替你啟動 server。首次準備遠端可使用 `herdr machine add build-box`，並自行確認原生提示。

若提示驗證或主機金鑰問題，先依主機管理者的方式核對身分，再在互動終端使用：

```sh
herdr machine reconnect PROFILE_ID
```

這個指令用於原生驗證與連通檢查，不是自動更新或重啟 server。不要關閉 SSH host-key checking 來排除錯誤。

慢速網路可調整 `herdr-pane --timeout 20`。這是每個查詢的期限，不是保證整份清單只花 20 秒；最多並行八個查詢，並另核對本機呼叫端。單一來源失敗仍會顯示其他可用結果。

## 清單沒有預期的 agent

確認 profile 已啟用，且指向正確帳號與 session。每筆 profile 只對應一個 session；在其他 session 工作不會自動出現在這筆連線裡。

本工具只列 Herdr 辨識的 agent，不列純 shell。可用原生 `herdr agent list` 或 `herdr --machine PROFILE_ID agent list` 比對，再確認 Herdr 的 agent 辨識狀態。不要將顯示為 idle 當成可以代答任何核准視窗。

## 選號後拒絕連線

目標已結束、terminal ID 改變、profile 被修改／停用，或無法核對身分時，工具會返回選單；刷新後重新選號。

本機會檢查程序祖先，避免接上執行啟動器的同一個終端。遠端也會查目標程序；若 PID 與呼叫端重疊，會在 SSH 連線中追加同機核對，只有確認是呼叫端自己時才拒絕，不把不同主機的 PID 巧合當成相同終端。查不到必要程序資訊時會拒絕 attach，不依其他視窗焦點猜測。

## 已被占用、斷線或被接管

一個終端僅能有一個 writable direct attach 擁有者。原生可能提示 takeover，但本工具不會替你接管；先與目前使用者協調交接。

正常 detach 會結束程式。其他錯誤會保留原生 Herdr／SSH 訊息並返回選單，由你決定是否重新連線；不自動重試。被接管後若原生 attach 沒自行返回，手動 detach 離開。

## 在 Herdr 裡如何 detach

Direct attach 使用 `Ctrl+B` 後按 `Q`，與完整 Herdr UI 的自訂前綴可能不同。若外層也使用 `Ctrl+B`，該按鍵可能先被外層接收；需要依外層的「傳送原始前綴」方式將它送入內層，通常是先按兩次前綴，再按 Q。所有巢狀終端組合尚未逐一驗證。

不確定時，可先在獨立終端視窗執行 `herdr-pane`，避免多層前綴。Detach 不會停止目標 agent。

## 遠端找不到 Herdr

`remote Herdr not found`／exit 127 代表 attach 使用的非互動 shell 找不到執行檔。請確認遠端 PATH 或原生安裝位置；程式會探索常見直接安裝、Homebrew 與 Nix profile 路徑，但沒有涵蓋所有自訂版本管理器。此版遠端腳本需要 POSIX shell。

## 移除或停用遠端

```sh
herdr-pane --remove-remote             # 選號後確認
herdr-pane --remove-remote PROFILE_ID  # 指定 ID 後確認
```

0.2.0 起 `herdr-pane -h` 會列出這些入口。若看不到，先用 `herdr-pane --version` 檢查版本，再依 README 更新安裝；shell 可用 `command -v herdr-pane` 確認執行位置。

移除時不接受主機標籤代替 ID；需要 ID 可用 `herdr machine list --json`。若提示設定已變更，重新執行選單核對。若移除命令已執行但結果無法確認，先查原生清單，不要將它當成已成功或未成功。

也可直接使用 `herdr machine remove PROFILE_ID`。

只想暫時隱藏時用 `herdr machine disable PROFILE_ID`，之後用 `herdr machine enable PROFILE_ID` 恢復。這些操作不停止遠端 session；重新啟動選單或按 `r` 反映變更。

## 回報問題

可提供作業系統、Python／Herdr 版本、使用哪個指令，以及自行去識別化後的錯誤碼。請不要公開 token、SSH config、真實主機／帳號／目錄、完整 process-info、session 快照或終端截圖。安全邊界見 [安全說明](security.md)。

原生命令依據：[Herdr 0.9.5 CLI](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/docs/next/website/src/content/docs/cli-reference.mdx)、[遠端與直接終端連線](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/docs/next/website/src/content/docs/persistence-remote.mdx)。

## 中斷、終端狀態與巢狀環境

選單中按 Ctrl+C 會取消；接上終端後仍以 Ctrl+B、Q detach，Ctrl+C 可能會送給目標程式。啟動器收到 SIGINT 時會先讓子程序清理，再於必要時結束它，並還原原先的終端設定。若輸入已經不顯示，可在可用的 shell 執行 `stty sane`。

新增／移除的原生命令已開始執行後，中斷不表示設定一定沒改變。工具會提示用 `herdr machine list --json` 確認結果，不會宣稱操作已回復。

自我辨識以直接在 Herdr pane 或一般終端執行為驗證範圍。tmux、screen、zellij，以及先透過 SSH／mosh 繞回同一台機器再執行，可能切斷程序祖先關係；本版不提供這些巢狀情境的防循環保證。請直接在 Herdr pane 執行，避免將包住呼叫端的終端接回自身。

若舊版本或未支援的巢狀環境已發生自接卡住，從另一個終端以 `herdr pane process-info --pane PANE_ID` 找出剛啟動的 attach client，再以 `ps -p CLIENT_PID -o pid=,ppid=,command=` 核對，對該 client 使用 `kill -INT CLIENT_PID`，無法退出時再使用 `kill -TERM CLIENT_PID`。這裡的目標是 attach client，不是 Herdr server 或正在工作的 agent。

若本機 `ps` 無法執行或祖先鏈不完整，本版連 `--list` 也會停止，避免顯示未能排除自身的清單。遠端程序 ID 恰與呼叫端相交時，遠端必須能執行本機選定的 `/bin/ps` 或 `/usr/bin/ps`；路徑不存在、無法查詢或 PID 超過遠端平台範圍，都會拒絕本次連線。Linux 與不同作業系統間的這些組合尚未實測。
