# herdr-pane

### 一張清單，接上本機與遠端的 agent。

把本機與已設定遠端的 agent 放在同一個選單。看見主機、名稱與狀態，輸入編號，就接上原本的工作終端。

> **目前狀態：0.1.0 可執行版本。**
> 已提供本機／遠端 agent 清單、當次選號連線與原生遠端設定引導。範例全部使用虛構資料；實測範圍與尚待驗證項目見 [驗證紀錄](docs/document-review.md)。

![herdr-pane：從本機與遠端收集 agent，選號後接上原終端](docs/diagrams/svg/00-overview.svg)

## 安裝

需要 Python 3.9 以上、Herdr 與 OpenSSH；本版支援 macOS／Linux 終端，遠端主機也須提供 POSIX shell。無需額外 Python 套件或 jq。

先下載或 clone 本 repository，進入專案目錄後執行：

```sh
mkdir -p "$HOME/.local/bin"
install -m 755 herdr_pane.py "$HOME/.local/bin/herdr-pane"
```

確認 `~/.local/bin` 已在 PATH；若尚未設定，可先以 `~/.local/bin/herdr-pane` 執行。

## 使用方式

```sh
# 列出本機與已設定遠端的 agent，輸入編號接上
herdr-pane

# 只看清單
herdr-pane --list

# 第一次設定遠端：跟著引導完成連線
herdr-pane --add-remote

# 已經知道 SSH 位置時，可以直接帶入
herdr-pane --add-remote developer@build.example.invalid
```

簡化選單示意（不是實際 session 資料）：

```text
  #  主機        Agent   名稱           狀態      目錄
  1  local       Claude  docs-review    idle      ~/projects/sample-docs
  2  local       Codex   app-build      working   ~/projects/sample-app
  3  build-box   Claude  remote-review  idle      ~/projects/sample-app

選擇編號，直接按 Enter 取消：3
```

編號只對應這次顯示的清單。選取後會再次確認目標，避免清單變動造成誤連。

## 文件導覽

| 想了解什麼 | 文件 |
| --- | --- |
| 列出、選號、連線與離開的完整流程 | [操作流程](docs/workflows.md) |
| 新使用者如何設定遠端 | [首次連線指南](docs/connection-guide.md) |
| 分享方式與公開資料的邊界 | [安全與發布檢查](docs/security.md) |
| 實作完成後要驗證哪些情境 | [驗收清單](docs/acceptance.md) |
| 編輯或重製流程圖 | [圖表原稿與製作方式](docs/diagrams/README.md) |

## Detail items

- **一個入口**：預設開啟互動選單，整合本機與所有已啟用遠端連線中的 agent。
- **選號即連線**：本機直接接上；遠端使用所選連線設定中的 SSH 目標與 session。
- **第一次也有引導**：`--add-remote` 收集 SSH 位置，交由 Herdr 原生互動流程設定。
- **局部失敗仍可用**：某台遠端離線，不影響其他可用的 agent。
- **可攜的設定**：程式使用工具探索與連線設定，不寫死開發者的帳號、家目錄或主機位置。
- **單一正式名稱**：只提供 `herdr-pane`，不建立舊名稱的相容入口。

「已設定遠端」指 Herdr 儲存且啟用的機器連線；每筆連線綁定一個遠端 session。本機預設使用呼叫端目前的 Herdr session。需要其他 session 時，必須明確切換或新增對應連線。

## Related functions

| 現有 Herdr 功能 | 在方案中的用途 |
| --- | --- |
| `herdr agent list` | 查詢指定 session 的 agent |
| `herdr machine list --json` | 取得已設定遠端的識別碼、SSH 目標與 session |
| `herdr --machine <profile> agent list` | 查詢遠端連線中的 agent |
| `herdr terminal attach <terminal_id>` | 接上已核對的終端 |
| `herdr machine add <ssh_target>` | 使用原生互動流程建立遠端連線 |

實作應確認實際安裝版本支援的命令與參數；不可只憑版本字串相同或不同判定相容性。

## Test results

```sh
python3 -m unittest discover -s tests -v
```

測試涵蓋多來源清單、設定／終端變更、逾時、輸入清理、選單快照、連線失敗不重試與新增遠端委派。實際驗證及限制見 [驗證紀錄](docs/document-review.md)；[驗收清單](docs/acceptance.md) 區分已驗證與待驗證項目。正式 staging 尚未執行。

## New components

`herdr_pane.py` 是可直接安裝的單檔程式，`tests/` 使用 Python 標準 unittest；另提供四張 SVG 與 Mermaid 原稿。程式不保存另一套 profile 或憑證，沒有新增服務或 CI。

## Reference

- [Herdr 官方文件索引](https://herdr.dev/llms.txt)
- [連接機器：設定、session 與失敗處理](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/docs/next/website/src/content/docs/connecting-machines.mdx)
- [遠端與直接終端連線](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.1/docs/next/website/src/content/docs/persistence-remote.mdx)

## Notes

這個工具提供終端連線便利性。接上 agent 後可以輸入操作；它不建立新的使用者權限，也不提供真正的唯讀存取控制。SSH 授權仍由主機擁有者管理。

選號只支援這次互動選單，不接受跨次執行的 `herdr-pane 1`。清單失敗可調整 `--timeout`（每個查詢預設 10 秒）；按 `r` 刷新，按 Enter 取消。
