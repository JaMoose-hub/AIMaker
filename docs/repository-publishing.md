# Repository 發布範圍

GitHub：<https://github.com/JaMoose-hub/AIMaker>。這是公開 repository，
不要提交個人登入資訊、工作階段照片或裝置密碼。

## 會提交

- `backend/app`、`frontend/src`、測試、schemas、firmware、scripts 與 tools。
- `pyproject.toml`、`uv.lock`、`package.json`、`package-lock.json` 等可重現依賴描述。
- 板卡／零件 profiles，以及定位功能依賴的參考圖與特徵資料。
- 使用說明、訓練工具與設定範本；不包含訓練資料本體。
- `backend/config.example.yaml`：無密碼、一般 webcam／CPU 的起始設定。
- `models/manifest.json` 明確列出的四個 ONNX：Pi 5 手持及重新定位、HC-SR04、MRD-TF240。

## 不提交

- `backend/config.yaml`：個人相機配置、Pi 主機與登入密碼。
- `.env*`（範例除外）、`.codex/`、`.ssh/`、認證／token 檔案及私鑰。
- `runs/`、`backend/runs/`、`datasets/`、相機校正、臨時截圖、AI 請求與結果、log。
- `.venv*`、`node_modules`、`dist`、快取、備份與訓練 checkpoint。
- HW-123、光敏電阻、其他板卡、分割模型、Eye 專用模型與舊版模型備份。

排除是 Git 規則，不會刪除本機資料。歷史文件可能連到未公開的 `runs/` 或資料集；
它們不是下載後執行三零件 webcam 流程的必要檔案。

## Codex bridge 與憑證

`backend/app/codex_bridge.py` 啟動本機 `codex app-server`，由 Codex 管理 ChatGPT 登入；
bridge 沒有內嵌 API key，也不讀取或匯出 Codex token。
執行工作使用暫存目錄；本機 Codex 認證不屬於本 repository。
下載者必須使用自己的帳號登入，請勿複製原作者的 Codex home／auth.json。

Pi 密碼預設為空，可以寫入已忽略的 `backend/config.yaml`，或由執行環境的
`BOARDVISION_PI_DEPLOY__PASSWORD` 提供；不要寫入程式碼或 commit 訊息。

## 每次 push 前

1. `git status --short`、`git diff --cached --stat` 確認待提交範圍。
2. `python tools/check_repository_publish.py` 檢查 Git index 的模型白名單、
   校驗碼、檔案大小與不應追蹤的路徑。
3. 使用 [Gitleaks](https://github.com/gitleaks/gitleaks) 掃描 index：

   ```powershell
   gitleaks git --pre-commit --staged --redact=100 --no-banner .
   ```

4. 只在掃描通過後 commit／push。不要用 `git add -f` 將本機設定強制加入。

`.gitignore` 不能保護已追蹤的檔案，也不是完整的金鑰掃描器。
若憑證曾經進入公開 commit，僅刪掉目前檔案還不夠，必須先撤銷／輪替該憑證。
