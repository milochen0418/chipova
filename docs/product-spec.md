> The blueprint Chipova is built from, as it was given (v1.0, 2026-10-26). What is built, verified, blocked or experimental, item by item: [status.md](status.md).

# Agentic IC Design Studio
## AI × 真人即時協作的開源晶片設計平台：產品、架構、UI 流程與 Agent 實作藍圖

**文件版本：** v1.0（供 AI Agent 啟動實作）  
**編製日期：** 2026-10-26  
**產品狀態：** 規格與路線圖；不是已完成的產品，也不是製程簽核保證  
**部署目標：** Reflex-based Agentic App Store（區域網路優先、可選遠端運算）  
**暫定產品名稱：** Agentic IC Design Studio（工作名稱；日後可換品牌名）

> **給 AI Agent 的一句話需求：** 建立一個可在 Agentic App Store 啟動的 Python Reflex Web IDE，讓多人與經授權的 AI Agent 即時共同編輯數位 IC 設計，從規格、RTL、驗證、合成與佈局繞線直到 GDSII／FPGA Bitstream；後續以可插拔容器化流程擴充類比／混合訊號、實體驗證、封裝規劃及實體測試。任何 Tape-out／Signoff 表述必須以已完成的規則、報告、審核與製程授權為依據。

---

# 0. Agent 啟動指示（必讀）

**優先順序：** 先完成「可多人編輯、可重現建置、結果可視化、AI 有人類審核」的垂直切片，再擴充 EDA 功能。不要一開始仿造完整 Cadence／Synopsys 桌面 IDE。

**必須遵循的 10 條規則：**

1. **Reflex 是產品殼層**：專案管理、身份、分頁、權限、共享狀態、Agentic App Store 的入口與整合均以 Python Reflex 為主。
2. **字元級同步用 CRDT**：Monaco Editor + Yjs + y-monaco + 授權的 WebSocket collaboration service。Reflex SharedState 管專案／房間層狀態，不用它單獨處理逐字協作衝突。
3. **SiliconCompiler 是數位 EDA Orchestrator**：採用當前 `Design`、`ASIC` 等 API；嚴禁抄用已被棄用的舊 `Chip()` 教學。
4. **EDA Job 必須容器隔離**：編輯器／Web 程序不得直接執行未受限的 `yosys`、`openroad`、`make` 或任意 shell 字串。
5. **建置使用不可變 Snapshot**：每次 Run 引用固定 `revision_id`、來源 SHA、工具版本、PDK 版本、容器映像 digest、參數與種子。
6. **人類與 Agent 操作要可追蹤**：AI 先提出 diff；人類可審閱、批准、復原。不可默默覆寫多人檔案。
7. **UI 顯示真實 Job 狀態**：未啟動、排隊、執行、失敗、通過、取消、等待審核；不得用假成功畫面。
8. **Signoff 不等於可量產**：DRC／LVS／STA／PEX 等各自獨立，且要求對應 PDK rule deck 與 foundry 接受標準。
9. **PDK／授權不可假設**：開源 PDK 可用於教學與驗證，不自動代表 foundry 允許商業 Tape-out。
10. **每個 UI 操作都要可驗收**：先定義使用者故事、狀態、資料結構、API 與自動測試，再完成介面。

**第一個必交成果**：一個可在兩個瀏覽器視窗共同編輯 Verilog、由 AI 提議修改、發起 Containerized Lint/Simulation、展示可追溯 Report 的可運作 MVP。

# 1. 產品定位與成功定義

## 1.1 產品願景

把「IC 設計工作流程」從個人、碎片化工具與文字終端轉為 **AI 和人共同使用的協作工作區**。使用者不必知道每一個 EDA CLI 的參數；但所有重要命令、輸出、版本與驗證狀態都可以被稽核和重現。

平台是 **EDA IDE + 協作層 + Agent 工具層 + 工作流程編排層 + 驗證證據層**；不是重新實作完整 EDA Kernel。

## 1.2 對象與使用場景

| 使用者 | 首要工作 | 平台核心能力 |
|---|---|---|
| RTL Engineer | Verilog/SystemVerilog 開發與 Testbench | 協作編輯、Lint、Simulation、Waveform |
| Verification Engineer | 功能驗證與回歸 | 測試矩陣、錯誤定位、CI 報表 |
| Physical Design Engineer | PPA、Floorplan、Routing、Timing | Flowgraph、Layout Preview、STA/DRC Report |
| Analog/AMS Engineer | 電路圖、SPICE、PVT 與 Layout | Xschem、ngspice/CACE、版圖與驗證 Adapter |
| Tech Lead / Reviewer | 設計審查與 Release | Diff、Approval Gate、Signoff Checklist |
| AI Agent | 提案、執行允許的工具、分析結果 | 受控 API、版本化提案、可查核記錄 |

## 1.3 成功與非目標

**MVP 成功**：兩人 + 一名 AI Agent 同時參與一個 Verilog 專案；兩人能看到彼此游標；AI 提出修正但不直接覆蓋；固定版號在容器內通過 Lint 與 Simulation；結果含可下載 Log、VCD 與來源 SHA；重新執行可以追溯相同輸入。

**Digital Alpha 成功**：指定開源 PDK 下完成 RTL → GDSII，能展示 Flowgraph、Metrics、Layout 與獨立的 DRC/LVS 報告；可導出完整、可重現的 Build Manifest。

**不屬於第一版**：真實 foundry 遞交、商業 PDK 相容承諾、進階類比互動式原理圖編輯器、EDA 工具全自製、SiliconCompiler CLI API 的穩定版本猜測、未驗證的物理量測數據。

# 2. 開源專案地圖與角色

以下「可直接支援」指具備工具或官方整合文件，**不等於零設定即能完整運作**；「要寫 Adapter」表示需由本專案實作容器呼叫、格式轉換、UI 與錯誤處理。專案名稱皆附原始碼網址。

## 2.1 數位設計與 IC 實作主幹

| 優先 | 專案與連結 | 在本平台的角色 | 整合策略 |
|---|---|---|---|
| P0 | [SiliconCompiler](https://github.com/siliconcompiler/siliconcompiler) | Python EDA Orchestrator、Flowgraph、Build Manifest | **後端核心**；目前 API `Design` / `ASIC` / `Sim` / `FPGA` |
| P0 | [Yosys](https://github.com/YosysHQ/yosys) | RTL 合成、轉網表 | 透過 SiliconCompiler / 容器執行 |
| P0 | [Verilator](https://github.com/verilator/verilator) | RTL Lint、模擬 | 經 SiliconCompiler Sim／Job Adapter |
| P1 | [OpenROAD](https://github.com/The-OpenROAD-Project/OpenROAD) | ASIC Floorplan、CTS、Route、STA、寄生參數／IR 分析 | SiliconCompiler ASIC backend |
| P1 | [KLayout](https://github.com/KLayout/klayout) | GDS/OASIS 版圖、DRC/LVS、圖層檢視 | 既有 EDA Flow + Layout Preview Adapter |
| P1 | [Magic](https://github.com/RTimothyEdwards/magic) | 版圖 DRC、Extraction | Signoff 工具，依 PDK 配置 |
| P1 | [Netgen](https://github.com/RTimothyEdwards/netgen) | LVS 比對 | 工具鏈內建或 Signoff Adapter；驗證目前版本流程 |
| P1 | [LibreLane](https://github.com/librelane/librelane) | 可比較的 RTL-to-GDSII 流程 | 第二條獨立 Pipeline／AMS Top Assembly 參考 |
| P1 | [Open PDKs](https://github.com/RTimothyEdwards/open_pdks) | 開放製程設定資料 | PDK Registry：SKY130 / GF180 / IHP SG13G2 |
| P2 | [nextpnr](https://github.com/YosysHQ/nextpnr) + [IceStorm](https://github.com/YosysHQ/icestorm) | FPGA P&R、Bitstream | SiliconCompiler FPGA Adapter，選定晶片 |

**驗證重點**：SiliconCompiler 官方 README 列明 ASIC APR 可透過 OpenROAD、FPGA APR 可透過 VPR/nextpnr；Signoff DRC/LVS 是獨立流程，不能與 P&R 的 DRC metric 混為一談。

## 2.2 類比、混合訊號與物理交付

| 優先 | 專案與連結 | 功能 | 整合策略 |
|---|---|---|---|
| P2 | [IHP SG13G2 AMS Chip Template](https://github.com/iic-jku/ihp-sg13g2-ams-chip-template) | AMS 範本、Padframe、Bondplan、DRC/LVS/PEX | **AMS 實作範本**；容器化 `make` 任務和報告匯入 |
| P2 | [IIC-OSIC-TOOLS](https://github.com/osic-tools/IIC-OSIC-TOOLS) | 一站式 EDA 容器環境、noVNC | 類比工具 Runner / 過渡式遠端桌面 |
| P2 | [Xschem](https://github.com/StefanSchippers/xschem) | 電路圖與 SPICE Netlist | 先提供檔案／遠端桌面整合；日後再做原生 UI |
| P2 | [ngspice](https://ngspice.sourceforge.io/) | 類比 SPICE 模擬 | Container Adapter：DC/AC/Transient |
| P2 | [CACE](https://github.com/efabless/cace) | PVT／Corners／參數驗證 | 統一測試結果 JSON 與報告視覺化 |
| P3 | [OpenFASoC](https://github.com/idea-fasoc/OpenFASOC) | 部分類比功能模組自動產生 | 特定 IP Generator；不是任意類比晶片合成器 |
| P3 | [GDSFactory](https://github.com/gdsfactory/gdsfactory) | Python 參數化 Layout 與資料轉換 | Optional Layout Automation 插件 |
| P3 | [OpenHTF](https://github.com/google/openhtf) | 封裝後板級／儀器測試流程 | 實體硬體測試端，與 EDA 簽核分離 |

**重要現況**：IHP AMS Template 官方聲稱具有 `make all` 流程，但其 README 也提到部分 full-chip LVS／Release 輸出仍有工作項目。Agent 必須根據當前 Commit 實際運行與收集 Log，不能將 README 的「tapeout-ready」字樣直接等同全面通過。

## 2.3 UI、協作與 AI 整合

| 優先 | 專案 | 功能 | 整合策略 |
|---|---|---|---|
| P0 | [Reflex](https://github.com/reflex-dev/reflex) | Python full-stack Web UI | 主應用 Framework |
| P0 | [Monaco Editor](https://github.com/microsoft/monaco-editor) | HDL 文字編輯、Diff、Problems | 包在 Reflex Custom Component |
| P0 | [Yjs](https://github.com/yjs/yjs) + [y-monaco](https://github.com/yjs/y-monaco) | CRDT 文字協作與共享游標 | 一個可編輯來源檔一個 Y.Doc／Y.Text |
| P0 | [Hocuspocus](https://github.com/ueberdosis/hocuspocus) | Authenticated Collaboration WebSocket | 自架 Relay；驗證 token 與 document ACL |
| P1 | [LiveKit](https://github.com/livekit/livekit) | 即時音訊、視訊、Agent 語音 | 與既有通訊 App 以 Intent 整合 |
| P1 | [WaveDrom](https://github.com/wavedrom/wavedrom) | 簡單數位波形繪製 | 小型訊號 Diagram；完整 VCD 可改用其他 viewer |
| P1 | [Surfer](https://gitlab.com/surfer-project/surfer) | Waveform 檢視 | 研究可否用其技術或遠端開啟；不預設可直接嵌入 Browser |
| P2 | [veryl2chip](https://github.com/ccc-eda/veryl2chip) | Veryl + Rust/WASM 的 EDA 教學 IDE | UI/FPGA 流程參考或獨立 Plugin，**不取代主要 EDA backend** |

**授權任務**：在 Fork、Bundle 或部署任何程式碼前，AI Agent 必須依所鎖定的 Commit 實際讀 `LICENSE`、NOTICE、第三方相依授權及 PDK 資料使用條款，產出 `THIRD_PARTY_NOTICES.md` 與 SBOM。上述表格不是授權法律意見。

# 3. 系統架構：UI、Collaboration、Agent、EDA 分離

## 3.1 邏輯架構

```text
Agentic App Store / SSO / Application Registry
                     |
            Reflex IC Design IDE
     +---------------+------------------+
     |               |                  |
  Project UI      AI Agent UI        Review UI
     |               |                  |
     +-------- API / Auth / ACL ----------+
                     |
          Collaboration Service
       (Yjs / y-monaco / Hocuspocus)
                     |
  Versioned Project Storage (Git + DB + Object Store)
                     |
            EDA Job Orchestrator
            (Queue / Containers)
             /               \
      Digital Pipeline      AMS Pipeline
      SiliconCompiler       IIC-OSIC-TOOLS
      Yosys / OpenROAD      Xschem / ngspice
      KLayout / Netgen      CACE / LibreLane
             \               /
           Artifacts + Evidence
      (VCD, reports, DEF, GDSII, DRC/LVS)
                     |
        Signoff Center / Release Gate
```

## 3.2 推薦技術分工

- **Frontend / Product Layer**：Reflex（Python）、以 Custom Component 接 Monaco 與必要的 JS 畫布；不得把整個專案改寫成另一套 JS SPA。
- **Realtime Layer**：Yjs CRDT 做 source text；Reflex SharedState 做多人 presence、room metadata、job state、review status；Hocuspocus 或相當服務處理連線授權和持久化。
- **Communication Layer**：LiveKit 用於通話或語音 Agent，可後接 Relack／Intent；不把 WebRTC 當作唯一檔案同步機制。
- **App API**：FastAPI/Reflex 允許的後端 endpoint 提供 project、snapshot、run、artifact、review、agent tool 操作。
- **Persistence**：PostgreSQL 儲存 metadata / audit；Git 儲存原始碼修訂；Object Store（MinIO/S3 compatible）儲存 Logs、VCD、GDS 等大檔。
- **Queue / Worker**：Redis Queue、Celery 或同等受控工作佇列；EDA Runner 在容器內執行、設定 CPU/RAM/時間/磁碟配額。
- **Digital Tooling**：SiliconCompiler 管理 EDA Flowgraph；保持每種工具的原始 log 與完整 metrics。
- **AMS Tooling**：先以既有容器和 Makefile 跑範本，逐步取代為可管理的 Adapter；無法從 Browser 原生呈現的工具先提供受控 noVNC 或結果檢視。

## 3.3 必須能替換的邊界

API 和 UI 不得寫死 `sky130`、`heartbeat` 或單一 Tool 版本。定義：`FlowProvider`、`PDKProvider`、`ArtifactRenderer`、`VerificationProvider`、`AgentToolProvider`。第一版只啟用必要 provider，其餘顯示「未啟用／尚未安裝」，不可偽裝成可用。

# 4. 產品導航、主要畫面與精確互動

## 4.1 Information Architecture（左側導覽）

1. **Projects**：設計清單、新建、匯入、權限、最近執行、Templates。
2. **Workspace / IDE**：Project Tree、HDL Editor、Schematic、Terminal（只讀建置）、Problems、Chat、Presence。
3. **Verify**：Lint、Simulation、Assertions、Waveforms、Test Matrix。
4. **Implement**：Synthesis、Floorplan、Placement、CTS、Routing、PPA。
5. **Layout**：GDS/DEF Preview、Layers、Cell Hierarchy、Measurement、Annotations。
6. **Signoff**：DRC、LVS、STA、PEX、IR、Antenna、Coverage、Waiver。
7. **Tape-out Package**：Build manifest、Checklists、Approval、Export、Foundry 協作資訊。
8. **Agents**：Agent Jobs、Suggested Patches、Plans、Permissions、Activity Log。
9. **Settings**：PDK Registry、EDA Containers、Run Quotas、Team & App Integrations。

## 4.2 核心 IDE 布局（桌面版）

```text
+-----------------------------------------------------------------------+
| Project / Branch / Revision | PDK | Collaborators | AI | Run | Share   |
+-------------+-------------------------------------+-------------------+
| EXPLORER    | Editor Tabs: rtl.v tb.sv constraints | AI / REVIEW       |
| Files       |                                     | Agent conversation|
| Specs       |   Monaco HDL + shared cursors        | Suggested diff    |
| Results     |   comments and source-line anchors   | Approve / Reject  |
| Runs        |                                     | Participants      |
|             +-------------------------------------+-------------------+
|             | Problems | Terminal Logs | Waveform | Run Progress      |
+-------------+---------------------------------------------------------+
| Status: Connected | Edited by Alice + Agent | Snapshot: abc...       |
+-----------------------------------------------------------------------+
```

**互動細節**：
- 使用者按 **Run Simulation**：先詢問使用「目前尚未提交的協作內容」建立 Snapshot，成功建立後才排入 Queue，顯示 Run ID。
- AI 提出 Patch：右側出現 Diff + 說明 + 影響檔案 + 驗證計畫；`Accept` 產生一筆可追溯變更，`Reject` 只記錄結果。
- 點 `Problems`：跳到 Monaco 行／列；點 Waveform 訊號可與 log 時刻對齊；點 Run Step 看到對應工具 log 和輸出檔。
- 多人同時檢視 Layout：分享 viewport、選取的 cell、annotations；不能讓多人直接同時覆寫同一 binary GDS。
- 右側 Agent 看到的內容須受權限限制，且其上下文要標出所依附的 `revision_id`。

## 4.3 各畫面規格、CTA 與空狀態

| 畫面 ID | 畫面 | 主 CTA | 核心顯示 | 空／失敗狀態 |
|---|---|---|---|---|
| UI-01 | App Store 啟動與登入 | `Open Studio` | SSO、Workspace | 無權限顯示 Request Access |
| UI-02 | Project Dashboard | `New Project` | Template、Owners、Last Run | 無專案時導向 Heartbeat Template |
| UI-03 | Collaborative IDE | `Run Lint` | Monaco、Presence、AI Diff | 斷線顯示 Reconnecting、Local Edits |
| UI-04 | Verification | `Run Simulation` | Test Results、VCD Viewer | 沒有 testbench 引導新增 |
| UI-05 | Implementation Flowgraph | `Build ASIC/FPGA` | DAG、Step、Metrics、Logs | Queue 狀態／失敗節點可重試 |
| UI-06 | Layout Workspace | `Open GDS Preview` | Layers、Hierarchy、Annotations | 尚無 GDS 顯示需要先完成 build |
| UI-07 | Signoff Center | `Run Checks` | DRC、LVS、STA、Waivers | 無 rule deck 顯示 BLOCKED，不顯示 PASS |
| UI-08 | Agent Center | `Request Proposal` | Plans、Diffs、Tool permissions | Tool 被拒應顯示原因 |
| UI-09 | Release / Tape-out Center | `Request Review` | 版號、Manifest、Approvers | 缺項不可送出 Approved 狀態 |
| UI-10 | Admin / Settings | `Register Tool Image` | Tools、PDKs、Quotas、RBAC | Missing license / container digest 提示 |

## 4.4 移動版策略

手機可做 Project 檢視、留言、AI 對話、Run 監控與 Approval；**不承諾手機上有完整的大型 GDS 編輯能力**。寬畫面優先提供 Editor + Layout + Waveform 的多面板體驗。

# 5. 核心使用者流程：四條工作旅程

## FLOW-DIGITAL：數位 RTL → GDSII

1. 新建 `Digital ASIC` Project → 選 Heartbeat Template / `SKY130` 及允許的工具版本。
2. 邀請真人團隊，角色設定 Owner / Editor / Reviewer / Viewer。
3. 在 IDE 寫 RTL、Testbench、SDC；多人游標、留言、分支可見。
4. AI 讀規格後提出 Patch、Testbench 與驗證清單；真人 Approve 才套用。
5. `Lint` → `Simulation` → `Waveform` → Assertions / Tests。
6. `Freeze Snapshot` 產生 SHA 與可重現 Revision，再選 `Build ASIC`。
7. EDA Worker 用 SiliconCompiler Flowgraph 執行合成／Place／CTS／Route／STA。
8. `Layout Workspace` 檢視 GDS Preview、PPA Metrics、Critical Paths。
9. `Signoff Center` 執行 DRC、LVS 等，核對 PDK deck 與 run status。
10. `Release Center` 將 Manifest、設計檔、報告、Approval 打包為 **Tape-out preparation package**。

**出口條件**：設計者可以查出每個結果對應的完整 Source / Tool / PDK 版本。若 signoff 不完整，不可將 status 設為 `FOUNDRY_READY`。

## FLOW-FPGA：RTL → FPGA Bitstream

1. 從同個 Project 選 FPGA Target（iCE40 等已支援裝置）。
2. 驗證 pins、clock、device package 配置，執行 Yosys + nextpnr + Bitstream packer。
3. 顯示 P&R/TIming、下載 `.bin` 或目標板可用格式。
4. 實體燒錄需要連接專門 Hardware Worker，由受授權人員啟動；Browser 不直接宣稱可以操作所有板卡。

## FLOW-AMS：類比／混合訊號

1. `Analog/AMS` Project → 指定 IHP SG13G2 Template 及對應 IIC-OSIC-TOOLS 映像。
2. Xschem（優先整合受控 noVNC／file exchange）建立 schematic 和 SPICE netlist。
3. 執行 ngspice DC/AC/Transient + CACE corner 測試，將數值與圖表回傳 Portal。
4. 匯入或產生 Analog Macro Layout，執行 DRC/LVS/PEX，保存規則和報告。
5. 數位區塊從 LibreLane 或 SiliconCompiler 產出 hard macro；整合 Padframe／Top Level。
6. 對整顆晶片執行 full-chip checks，產出 GDS、Netlist、Bondplan 與 review evidence。

**最重要的限制**：AMS Template 的現行 README 記錄部分 Full-chip LVS/Release 的待辦，因此 Agent 第一件事應重跑指定 commit 的 Make Targets，再報告真實差距。

## FLOW-POSTSILICON：封裝與測試

1. `Package Planning` 記錄 Package Type、Pin Map、Bond Diagram 及 Foundry / OSAT 條件。
2. 合格授權使用者核准封裝設計及輸出；對外提交由人類負責。
3. 製造後使用 OpenHTF 及適當儀器／測試板記錄實測；Results 回傳 Project。
4. 用 Dashboard 對比 Pre-silicon 規格和 Post-silicon 量測；報告明確區分兩者。

# 6. 即時協作與版本管理規格

## 6.1 文件同步機制

- 每個文字檔 `project_id:file_path` 為獨立 Document ID；Yjs 處理同時編輯、斷線重連及游標 awareness。
- 文件儲存要持久化、支援 compaction 和 Crash Recovery；不可僅依賴 Browser localStorage。
- SharedState 只傳 `project_state`、`users_online`、`active_run_id`、`selected_revision` 等粗粒度狀態。
- Binary Artifact（GDS、DEF、WDB）不可用 Y.Text 同步；採版本化上傳和 immutable artifact。
- 人類可對檔案、行號、Cell、Run Step、Violation 加 comment thread；Review 應錨定特定 revision。

## 6.2 版本的三個概念

- **Working Copy**：持續變動的協作文件；可顯示 dirty 狀態，**不是可重現的建置輸入**。
- **Snapshot / Revision**：凍結後的來源樹、參數、commit/hash；EDA Run 的唯一輸入。
- **Release**：已通過指定 Gate 並有 Approval 的一組不可變 Revision + Artifacts。

**衝突策略**：RTL 文字交給 CRDT；SDC、專案參數與 PDK 設定若同時修改則採 optimistic concurrency + diff review；Binary file 採 explicit lock 或新版號。

# 7. AI Agent 能做什麼、不能做什麼

## 7.1 Agent 角色分工

| Agent | 任務 | 工具權限 |
|---|---|---|
| Spec Agent | 規格理解、需求與測試矩陣提案 | 讀專案、提出文檔 Patch |
| RTL Agent | RTL / Testbench 修改建議 | 讀 Source、提出 Diff，不能未審核直接 Merge |
| Verify Agent | 解析模擬失敗、定位 assertion | 執行批准的 Lint/Sim，讀 log/VCD |
| Physical Agent | PPA、STA、floorplan 建議 | 讀 metrics/report，提議 flow parameters |
| Signoff Agent | 整理 DRC/LVS/STA 證據 | 讀報告、產生 checklist，不得獨立簽核 |
| Release Agent | 打包交付資料與比對 manifests | 只可建立 Release Candidate，需人類 Approver |

## 7.2 工具呼叫需受控

建議最小工具契約（JSON 意義說明）：

```json
{
  "tool": "eda.submit_run",
  "args": {
    "project_id": "p-001",
    "revision_id": "sha256:...",
    "flow_id": "rtl_sim",
    "tool_profile_id": "verilator-pinned-v1",
    "parameters": {"test_suite": "smoke"}
  },
  "requested_by": "agent:verify-01",
  "approval_id": "appr-optional"
}
```

**安全約束**：所有 `project_id`、`revision_id`、`flow_id`、`tool_profile_id` 都從允許清單解析；對 EDA Agent 不提供 unrestricted shell；檔案路徑要防 traversal；Run 採 CPU/RAM/Time/Disk/Network 限制；敏感 PDK 不得送往未經授權的第三方 LLM；所有 Tool Invocation 記錄 identity、args、artifact hash、decision。

## 7.3 Agent UI 行為

- `Plan`：任務目標、預計修改檔案、測試策略、依賴與風險。
- `Propose`：Unified Diff、設計說明與受影響 Testbench。
- `Review`：人類 Approve/Reject/Request changes。
- `Execute`：只跑已批准且可追溯的 Job。
- `Explain`：引用實際 Log 的檔名／行號和工具步驟，不能憑空宣稱 DRC Clean。
- `Learn`：只能儲存可公開的工具使用經驗；私有 IP、PDK 和設計材料採專案權限隔離。

# 8. 介面、資料模型與後端契約

## 8.1 核心資料表／模型

| Entity | 最少欄位 | 不變量 |
|---|---|---|
| `Project` | id, name, type, owner, pdk_profile, created_at | PDK 設定可版本化 |
| `Membership` | project, user, role, permission_set | 每個 WebSocket document 需驗證 ACL |
| `Revision` | id, project, git_commit, source_sha, created_by | 不可變 |
| `FlowDefinition` | id, type, tool_profiles, schema_version | 需有版本 |
| `Run` | id, revision_id, flow_id, status, requested_by, started_at, ended_at | 不可引用 Working Copy |
| `RunStep` | run_id, node, status, command_digest, metrics | 可定位原始 Log |
| `Artifact` | id, run_id, kind, sha256, size, uri, access_scope | 不可由其他專案直接讀取 |
| `AgentAction` | id, agent, kind, proposal, approved_by, status | 有人類審核紀錄 |
| `Review` | id, revision_id, reviewer, status, comment | 不可對其他 Revision 套用 |
| `SignoffCheck` | id, run_id, rule_deck, status, waivers, reviewer | `NOT_RUN` 不能顯示 PASS |

## 8.2 建議 REST/WebSocket Endpoint

```text
POST   /api/projects                     # Create project from template
GET    /api/projects/{id}                # Detail + permissions
POST   /api/projects/{id}/snapshots      # Freeze collaborative working copy
GET    /api/projects/{id}/revisions      # Source + configuration history
POST   /api/projects/{id}/runs           # Lint/Sim/ASIC/FPGA/AMS
GET    /api/runs/{run_id}                # State, metrics, steps
GET    /api/runs/{run_id}/events         # SSE or authorized WS
GET    /api/runs/{run_id}/artifacts      # Signed scoped artifacts
POST   /api/projects/{id}/agent/propose  # Human-reviewed patch proposal
POST   /api/agent-actions/{id}/approve   # Approval by authorized user
POST   /api/projects/{id}/reviews        # Review on revision
POST   /api/projects/{id}/releases       # Gated release request
GET    /api/projects/{id}/signoff        # Version-scoped checklist
WS     /collab/{project_id}/{file_id}    # Yjs protocol + ACL
```

**Job State Machine**：`CREATED → QUEUED → RUNNING → {SUCCEEDED | FAILED | CANCELED | TIMED_OUT}`；Approval 是另外一條狀態機 `PROPOSED → {APPROVED | REJECTED | EXPIRED}`，不能用 Run 成功推導人類已批准。

## 8.3 產物與命名

```text
projects/{project_id}/revisions/{revision_id}/source/...
projects/{project_id}/runs/{run_id}/manifest.json
projects/{project_id}/runs/{run_id}/steps/{node}/stdout.log
projects/{project_id}/runs/{run_id}/steps/{node}/metrics.json
projects/{project_id}/runs/{run_id}/artifacts/{name}.{vcd|gds|def|json|rpt|bin}
projects/{project_id}/releases/{release_id}/approval.json
```

Report Normalizer 對資料定義：`severity`、`tool`、`step`、`source_location`、`metric`、`value`、`unit`、`artifact_ref`；原始 log 不可丟棄。所有示意 schema 應在第一個 Sprint 制定正式版本並用 Pydantic 驗證。

# 9. Digital EDA Adapter 實作策略

## 9.1 SiliconCompiler 官方新 API（參考，不要硬編碼到所有專案）

官方 Quickstart 的 Heartbeat ASIC Python API 方向如下；Agent 必須先閱讀目前鎖定版本文件，再在容器內實際執行。

```python
from siliconcompiler import ASIC, Design
from siliconcompiler.targets import skywater130_demo

design = Design("heartbeat")
design.set_topmodule("heartbeat", fileset="rtl")
design.add_file("heartbeat.v", fileset="rtl")
design.add_file("heartbeat.sdc", fileset="sdc")

project = ASIC(design)
project.add_fileset(["rtl", "sdc"])
skywater130_demo(project)
project.option.scheduler.set_name("docker")
project.run()
project.summary()
```

**產品化差異**：上述為示範用法；真正服務要將輸入放在版本化工作目錄、提供 snapshot hash、容器 images pinned digest、控制執行資源、儲存 Artifact 與 log，透過工具 Adapter 上傳結果，不要讓 Web Worker 直接呼叫 `project.run()` 阻塞請求。

## 9.2 Runner 合約

1. Controller 接收 Run Request，檢查權限、Quota、PDK License。
2. 產生 Workspace（唯讀 source、唯讀 PDK、可寫 output）；檢查 manifest integrity。
3. Worker 以固定 Container 執行精確命令或 Python Entry Point；禁止混入 Shell 字串。
4. 收集 stdout、stderr、metrics、report、GDS／DEF／VCD、Return Code、Tool Versions。
5. 正規化 Run Steps，並以 WebSocket / SSE 通知 UI。
6. 驗證產物 hash，將最終狀態設為成功或失敗；失敗時保留 Log 與局部 Artifact。

## 9.3 Layout Preview 原則

第一版**不要求在瀏覽器製作功能等同 KLayout 的 GDS 編輯器**。使用 KLayout 的 Script／CLI 產生總覽 PNG／SVG 或 tile/pyramid 預覽；Browser 顯示 layer、hierarchy、zoom、pan、annotation，附 Download GDS 與 Open Native Viewer；後續再研究互動式幾何瀏覽。必須標明 Preview 不是可靠的 DRC/LVS 結論。

# 10. Signoff、PDK 與 Tape-out Preparation

## 10.1 Signoff 狀態模型

每項 Check 有 `NOT_CONFIGURED / NOT_RUN / RUNNING / PASS / FAIL / WAIVED / BLOCKED`。`WAIVED` 需要理由、審核者、時間、Rule ID、所依據 Revision，並不得自動轉成 PASS。

| 類別 | 檢查對象 | 必存證據 |
|---|---|---|
| DRC | GDS 對 PDK Layout Rules | Deck 版本、違規數、坐標、Report |
| LVS | Extracted vs Intended Netlist | PDK/Netlist 版本、配對結果、差異 |
| STA | SDC / Corners / Extracted RC | Critical paths、WNS/TNS、時序報告 |
| PEX | 寄生參數萃取 | 提取格式、模型、corner、報告 |
| Power/IR | 功耗、供電品質 | 方法、Corner、模型及限制 |
| Antenna/DFM | 製造相關規則 | 來源 Rule Deck 與 violations |
| AMS PVT | DC/AC/Transient/Corners/MC | Circuit version、模型、測試數據 |
| Full-chip | Padframe、Top-level、IO、Macro | Cell hierarchy、視覺資料、實際檢查結果 |

## 10.2 Tape-out Release Gate

- 必須有選定的 Foundry/MPW 要求清單及其版本；不直接把任一開源 PDK「PASS」當成正式 Foundry Signoff。
- 交付包至少包括 GDS/OASIS、netlists、LEF/Liberty（若適用）、SDC、Rule deck/version、DRC/LVS/STA/PEX 報告、Pinout/Padframe/Bondplan、BOM/Package Plan、Release Manifest、Approvals。
- Reviewer 身分與 Approval 要獨立於提出 Patch 的 Agent；AI 只能建議準備度，不可簽署法定或商業製程保證。
- 商業 PDK 常有 NDA 與可用範圍限制；授權資料不得隨使用者自由分享或送到未經允許的外部 AI。

**SKY130 特別註記**：其官方公開文件將開源 PDK 定義為 Experimental Preview，不保證可以用於量產；因此初期以驗證能力／測試晶片為目標，生產資格必須另行確認。

# 11. 開發路線圖（按驗收成果，不按虛構工期）

## Phase 0：基礎與可重現環境

**Tasks**：建立 Reflex app scaffold；App Store/SSO Adapter；資料模型；容器映像管理；Git / object storage；CI；Reference RTL Template；技術決策文件 ADR。  
**Exit**：一鍵啟動前後端、建立/開啟專案、執行假資料以外的實際 Lint Job；CI 與日誌可追蹤。

## Phase 1：多人 + AI 協作 Digital IDE（MVP）

**Tasks**：Monaco + Yjs；同步游標；權限；檔案管理；Snapshot；Agent Patch + Review；SiliconCompiler Lint/Sim Adapter；Log/VCD；基本 Run Dashboard。  
**Exit**：兩位工程師同時修改同一檔案不丟字；AI 提議變更、經批准後上版；真實 Lint/Sim Artifact 可下載；失敗錯誤可跳到檔案行號。

## Phase 2：ASIC / FPGA Full Flow 與可視化

**Tasks**：Container SiliconCompiler ASIC target；OpenROAD/ KLayout Metrics；Flowgraph；Layout Preview；FPGA nextpnr Adapter；比較不同 Runs 的 PPA。  
**Exit**：公開範例重現 RTL → GDSII 與 RTL → FPGA bitstream；每個 Run 保存 Hash、PDK/Tool Versions；報告展示客觀數據。

## Phase 3：Signoff Center 與審核流程

**Tasks**：KLayout、Magic、Netgen、STA/PEX checks；Waiver；Review Approval；Release Manifest；Artifact Integrity Check。  
**Exit**：可對同一 Revision 執行配置齊全的檢查，Fail/Blocked/Not Run 不會誤顯 PASS；Release Gate 可阻擋未完成 Checklist。

## Phase 4：Analog / AMS 與 Top-level Assembly

**Tasks**：IIC-OSIC-TOOLS Container、IHP AMS Template Adapter、Xschem 導入、ngspice/CACE Results、Macro Integration、Padframe/Bondplan。  
**Exit**：官方 IHP Template 指定版本可在受控環境重現部分或完整流程，能清楚區分通過、略過、待人工處理與尚未驗證的步驟。

## Phase 5：Post-silicon / Ecosystem

**Tasks**：OpenHTF 實體測試 Adapter；測試儀器與板卡；量測資料匯入；Relack/LiveKit 意圖串接；可選 FPGA Flash Worker；各 EDA Plugin Marketplace。  
**Exit**：至少一項真實儀器測試／板卡測試的結果可和 Pre-silicon Revision 關聯，且完整保存量測配置。

# 12. 功能驗收條件（Acceptance Criteria）

| ID | Given / When / Then | 必須驗收 |
|---|---|---|
| AC-01 | 兩人同時編輯同一 RTL，第三人即時觀看 | 內容一致、游標標註正確；斷線可恢復 |
| AC-02 | AI Agent 提出會修正測試的 diff，使用者拒絕 | Source 不變、記錄拒絕原因 |
| AC-03 | AI Agent 提出 Patch，Approver 同意 | 產生可追蹤變更與新版 Snapshot |
| AC-04 | Lint/Sim 遇到 RTL 語法錯誤 | Run=FAILED，保留 log，跳轉出錯行 |
| AC-05 | Simulation 產生 VCD | 瀏覽器顯示真實 Waveform，Artifact 可驗 hash |
| AC-06 | 對同個 Revision 重跑 Build | 顯示工具／PDK／設定相同與否；不同時明確比較 |
| AC-07 | DRC Deck 未設定 | UI 顯示 BLOCKED，不得顯示 PASS |
| AC-08 | 模擬與 ASIC Build 各產生 Artifact | Flowgraph 節點與 Artifact 正確關聯 |
| AC-09 | Viewer 嘗試讀私有 Project Artifact | API、WS 均拒絕，留下 Audit 記錄 |
| AC-10 | Agent 嘗試執行未允許 shell 命令 | 工具調用被拒，Container 不啟動 |
| AC-11 | Release Candidate 缺 LVS 或 Approval | Release Gate 阻擋，列出缺件 |
| AC-12 | 類比 Container Build 失敗 | 保留 make log，UI 標明未完成，不能推論「Tape-out-ready」 |

**性能基準（先訂測試而非承諾數值）**：多人同步延遲、重新連線成功率、Artifact 上傳／下載完整性、Run 排隊時間、Container 中斷恢復、Build 可重現程度與大型 GDS 預覽載入時間。測試需記錄實際硬體條件與量測方法。

# 13. 安全、可靠度與合法使用

- **IP / Data Isolation**：組織與 Project 隔離；RBAC + ABAC；WebSocket、API、Object Storage 三層都驗權限。
- **Agent Isolation**：工具最小權限、批准流程、Prompt Injection 防護、Agent 工具呼叫稽核、避免 Model 看見未授權專案。
- **Container Isolation**：rootless／受限 user、CPU/RAM/Disk/timeout、唯讀掛載、網路預設拒絕、Secret 注入與輪替。
- **Licenses**：每一個第三方依賴與 PDK 需要 README+LICENSE+NOTICE+來源版本清單；商業使用需審核義務。
- **Artifacts**：每個下載要權限和簽名 URL；不應讓任何協作者透過猜測路徑取得 GDS 或 NDA 資料。
- **Safety in release**：無法以 AI 的推理取代 Foundry Signoff、封裝可靠性、E-test/ATE、實測；僅由有權限人員核准對外發送。
- **Reproducibility**：對每次 Run 產生 SPDX/CycloneDX SBOM（若適用）、執行參數、Container Digest、依賴版本與完整 Artifact 索引。

# 14. 建議 Repository 結構（供 Agent 實作）

```text
agentic-ic-studio/
  README.md
  AGENTS.md
  LICENSE                    # 本專案授權另行決定
  THIRD_PARTY_NOTICES.md
  docs/
    product-spec.md
    architecture.md
    adr/
    ui-flows.md
    e2e-test-plan.md
  app/                       # Reflex app
    pages/
    components/
      monaco_collab/
      wave_viewer/
      layout_preview/
      flowgraph/
    state/
    auth/
    agents/
  services/
    api/
    collab/                   # Yjs collaboration service
    jobs/
    adapters/
      siliconcompiler/
      iverilog_verilator/
      openroad_klayout/
      ams_template/
      ngspice_cace/
    artifacts/
    signoff/
  domain/
    models/
    schemas/
    events/
  templates/
    digital_heartbeat/
    fpga_blinky/
    ams_inverter/
  infra/
    compose/
    dockerfiles/
    pdk_registry/
  tests/
    unit/
    integration/
    e2e/
    security/
```

**建置原則**：若現有 Agentic App Store 已有 SSO／Registry／Relack／LiveKit 等共用服務，優先使用正式內部介面而非重新實作；先確認各服務的 Repo、API 與權限契約，再建立 Adapter。

# 15. 可直接複製給 Coding Agent 的開工任務

> **你的角色**：資深 Python Reflex Engineer + EDA Systems Architect + Collaborative Editor Engineer。你的任務是根據本規格書，交付可執行、可測試的 Agentic IC Design Studio，而非只有 Mockup。
>
> 
> **第一輪必須產出：**
> 1. `docs/architecture.md`：清楚劃分 Reflex、Collaboration、EDA Worker、Agent Tool、Object Store。
> 2. `docs/ui-flows.md`：Project Dashboard、Collaborative IDE、Verification、Run Dashboard 的頁面樹、狀態與 CTA。
> 3. `docs/adr/0001-core-decisions.md`：說明選用 SiliconCompiler、Monaco/Yjs、Container Runner 的取捨及替代方案。
> 4. `app/`：可運行的 Reflex App，含建立 Project、開啟多頁 IDE、基本存取控制。
> 5. `app/components/monaco_collab` + `services/collab`：兩瀏覽器共同編輯並顯示游標、重連後保持一致。
> 6. `services/jobs/adapters/siliconcompiler`：可對固定 Snapshot 執行真實 Lint/Simulation，收集 log/VCD。
> 7. `services/api/`：正式 Pydantic request/response schema 與 Run State Machine。
> 8. `tests/`：至少覆蓋協作、Agent Patch Approval、失敗 Job、權限、Artifact Hash 的測試。
>
> **禁止**：假造成功的 EDA log、把假 PNG 當真 GDS Preview、硬寫假工具版本、將未通過的 signoff 宣稱為 PASS、直接在 Web Server 裡執行 arbitrary shell、跳過 License/PDK 檢查、無人工審核就把 AI Patch 直接 Merge。
>
> **開發順序**：先列出實際讀過的上游 README / docs / LICENSE 和 pinned commits → 實作最小垂直切片 → 提供安裝與測試命令 → 執行測試 → 回報已通過項目與尚未驗證項目 → 再做視覺 polish。
>
> **完成定義**：使用者在 Agentic App Store 進入 IDE，邀請第二人協作，執行真正 EDA 測試，看到可追溯 Log、Run ID、Snapshot、Artifact，再讓 AI 提出 diff 並取得人工批准。若任一步做不到，需在 README 明示限制，不能用 Stub 宣稱完工。

# 16. 第一批 GitHub Issues（建議直接建立）

| Issue | 預期交付物 | 依賴 |
|---|---|---|
| IC-001：Reflex App Skeleton | Projects / IDE 基本路由與 CI | 無 |
| IC-002：RBAC/SSO Adapter | Project ACL / Membership | IC-001 |
| IC-003：Project + Git Snapshot | Revision SHA / diff / history | IC-001 |
| IC-004：Monaco Yjs Collaboration | 兩人協作、shared cursors、斷線恢復 | IC-002 |
| IC-005：Artifact Store | SHA-256、ACL、signed downloads | IC-002 |
| IC-006：EDA Job Engine | Queue / container / state / events | IC-003, IC-005 |
| IC-007：Lint + Simulation | Verilator via pinned Runner + log/VCD | IC-006 |
| IC-008：AI Patch Review | Agent propose/approve/reject flow | IC-003, IC-004 |
| IC-009：Verification UI | 問題定位、測試、波形 | IC-007 |
| IC-010：SiliconCompiler ASIC | Digital Heartbeat to GDSII | IC-006 |
| IC-011：Flowgraph + Metrics | 每步 Logs / PPA / status | IC-010 |
| IC-012：Layout Preview | 真實 GDS 輸出的縮放預覽 | IC-010 |
| IC-013：Signoff Dashboard | DRC/LVS/STA 狀態及證據 | IC-010 |
| IC-014：Release Gate | Approval + manifest + blocked states | IC-013 |
| IC-015：AMS Template Adapter | IHP 流程容器、報告匯入 | IC-006 |

# 17. 參考資料（請 Agent 先讀官方來源）

## SiliconCompiler / Digital

1. [SiliconCompiler Repository](https://github.com/siliconcompiler/siliconcompiler)
2. [SiliconCompiler Official Quickstart](https://docs.siliconcompiler.com/en/latest/user_guide/quickstart.html)
3. [SiliconCompiler AGENTS.md](https://github.com/siliconcompiler/siliconcompiler/blob/main/AGENTS.md)（特別注意 API 已更新）
4. [SiliconCompiler FPGA Tutorial](https://docs.siliconcompiler.com/en/latest/user_guide/tutorials/fpga.html)
5. [OpenROAD](https://github.com/The-OpenROAD-Project/OpenROAD)
6. [Yosys](https://github.com/YosysHQ/yosys)
7. [Verilator](https://github.com/verilator/verilator)
8. [LibreLane](https://github.com/librelane/librelane)
9. [KLayout](https://github.com/KLayout/klayout)
10. [Magic](https://github.com/RTimothyEdwards/magic)
11. [Netgen](https://github.com/RTimothyEdwards/netgen)
12. [SKY130 PDK Status](https://skywater-pdk.readthedocs.io/en/main/status.html)

## AMS / Layout / Packaging / Test

13. [IHP SG13G2 AMS Chip Template](https://github.com/iic-jku/ihp-sg13g2-ams-chip-template)
14. [IIC-OSIC-TOOLS](https://github.com/osic-tools/IIC-OSIC-TOOLS)
15. [Xschem](https://github.com/StefanSchippers/xschem)
16. [ngspice](https://ngspice.sourceforge.io/)
17. [CACE](https://github.com/efabless/cace)
18. [GDSFactory](https://github.com/gdsfactory/gdsfactory)
19. [OpenFASoC](https://github.com/idea-fasoc/OpenFASOC)
20. [OpenHTF](https://github.com/google/openhtf)

## Collaboration / Agent App

21. [Reflex](https://github.com/reflex-dev/reflex)
22. [Monaco Editor](https://github.com/microsoft/monaco-editor)
23. [Yjs](https://github.com/yjs/yjs)
24. [y-monaco](https://github.com/yjs/y-monaco)
25. [Hocuspocus](https://github.com/ueberdosis/hocuspocus)
26. [LiveKit](https://github.com/livekit/livekit)
27. [veryl2chip](https://github.com/ccc-eda/veryl2chip)

---

## 文件使用說明

這份文件是 **architecture + product requirements + agent execution brief**。每一個外部專案都可能更新 API、授權與支援裝置。AI Agent 應在開始實作時鎖定版本、重跑官方範例與測試，逐項填寫 `Implemented / Verified / Blocked / Experimental`，並於完成各階段時更新本規格。任何 Release 或 Tape-out 過程，仍需由具備相應授權和專業資格的人工審核。
