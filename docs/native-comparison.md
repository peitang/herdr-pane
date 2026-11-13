# 與原生 Herdr 的比較

`herdr-pane` 是第三方操作捷徑。Herdr 本身已經提供多機連線、跨機 agent 總覽、session 持續執行與單一終端 attach。本工具沒有實作新的遠端存取協定、使用者授權或共享 server。

本比較以 Herdr 0.9.5 官方文件與 `herdr-pane` 0.2.1 的實作為準。

## 哪些原本就有

| 需求 | 原生 Herdr | herdr-pane 的增量 |
| --- | --- | --- |
| 本機＋遠端 agent 總覽 | 原生側欄包含已連線機器與 agent | 提供一般終端可用的編號快照 |
| 搜尋名稱、狀態與路徑 | Goto picker 支援搜尋與篩選 | 本版沒有搜尋，只有編號 |
| 切到另一台機器的工作 | 側欄與跨機 workspace 導覽 | 不切換整個視窗，將單一終端接進目前 pane |
| 單一遠端終端 attach | 原生 direct attach，加上 SSH | 查詢目標並組合 SSH／session 參數，連線前再核對 |
| 新增遠端 | machine add；0.9.5 可探索執行中的 session | 詢問位置與 session 的簡單包裝 |
| 移除、停用、重新啟用 | 原生 machine remove／disable／enable | 移除提供選號、確認與前後核對；停用／啟用沿用原生命令 |
| 分享同一個 session | 原生 Herdr 與既有 SSH 存取 | 沒有新增存取權或邀請機制 |
| 斷線恢復與持續更新 | 完整 client 提供重連、狀態與通知 | 清單手動刷新；direct attach 不自動重連 |

原生跨機清單與管理方式見 [多機文件](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/docs/next/website/src/content/docs/connecting-machines.mdx)；搜尋與篩選見 [鍵盤操作](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/docs/next/website/src/content/docs/keyboard.mdx)。這裡沒有宣稱 Goto 搜尋一定跨越所有機器，因為文件沒有明確界定該搜尋範圍。

原生 CLI 的 `--machine` 一次選一台，不提供跨機合併清單，也不轉送互動式 attach。因此命令列路徑需要收集各來源，遠端 attach 再使用 SSH。見 [CLI 的 saved-machine 範圍](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/docs/next/website/src/content/docs/cli-reference.mdx)。

## 省下什麼操作

如果要把遠端某個 agent 接進正在使用的 pane，手動 CLI 通常需要：查對應機器與 session、查 agent／terminal ID、組合 SSH 與 attach 命令。`herdr-pane` 把這些操作收進「執行指令 → 選編號」，並重新核對快照，避免使用失效目標。

這適合左右並排本機與遠端 agent 的工作習慣。若已經在 Herdr UI 內切換工作，原生側欄與搜尋可能更方便。本專案沒有前後操作計時或效率百分比的測量，不能保證在所有情境更快；SSH 建立連線本身沒有因此加速。

## 需要承擔的取捨

- 多安裝一支 Python 程式，且需要維護 Herdr CLI／JSON 格式的相容性。
- 清單是當次快照，沒有原生 UI 的持續通知、搜尋與自動重連。
- 本版 `--add-remote` 一律明確指定 session；原生 0.9.5 的自動探索可能更適合第一次設定。
- 查詢使用原生 machine forwarding；真正 attach 另走普通 SSH。某些驗證設定可能需要再次驗證，不保證沿用 Herdr 管理的共享連線。
- 本機只查目前 session，每筆 profile 只查一個遠端 session，不是網路掃描器。

## 與其他人共用

使用者仍須有到達遠端的網路路徑與 SSH 權限，並連到有權存取目標 session 的帳號。工具不替主機擁有者授權，也不建立唯讀權限。

同一終端只有一個 writable direct attach 擁有者。若需求是多位使用者同時觀看完整工作區，應先評估 Herdr 原生多 client；本工具不擴大 direct attach 的擁有者限制。見 [原生 attach 與觀察介面](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/docs/next/website/src/content/docs/persistence-remote.mdx)。
