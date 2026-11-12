# 流程圖原稿

| 圖表 | SVG | Mermaid |
| --- | --- | --- |
| 產品總覽 | [00-overview.svg](svg/00-overview.svg) | [00-overview.mmd](source/00-overview.mmd) |
| 選號與連線 | [01-select-and-connect.svg](svg/01-select-and-connect.svg) | [01-select-and-connect.mmd](source/01-select-and-connect.mmd) |
| 新增遠端引導 | [02-add-remote.svg](svg/02-add-remote.svg) | [02-add-remote.mmd](source/02-add-remote.mmd) |
| 離開與異常處理 | [03-recovery.svg](svg/03-recovery.svg) | [03-recovery.mmd](source/03-recovery.mmd) |

SVG 是方便閱讀與分享的輸出；Mermaid 原稿是流程的維護來源。圖表僅使用虛構標籤，不含真實 session 或環境資料。

## 視覺約定

- 藍色：使用者操作與主要步驟。
- 青綠色：成功結果與可用狀態。
- 琥珀色：條件判斷、等待或需要使用者處理。
- 淺紅色：不可直接繼續的錯誤。
- 灰色：返回、取消與正常結束。

圖中也用文字標示意義，不只靠顏色辨認。

## 重製

本批 SVG 使用 Mermaid CLI 11.4.2 產生。可在已配置 Mermaid CLI 與瀏覽器的環境，於 repository 根目錄執行：

```sh
mmdc -i docs/diagrams/source/00-overview.mmd \
    -o docs/diagrams/svg/00-overview.svg \
    -c docs/diagrams/theme.json -b '#f8fafc'
```

其餘圖表使用相同方式更換檔名。瀏覽器位置、快取與本機套件路徑留在個人環境，不寫進 repository。

輸出後應檢查：箭頭是否對應原稿、字形是否完整、有沒有裁切、SVG 是否包含非預期的外部資源或 metadata。圖表出現新的個人資料時，不可以因為是圖片就跳過掃描。
