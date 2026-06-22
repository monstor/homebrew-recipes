# 🍺 Homebrew Recipes

家釀酒譜版本管理與迭代記錄。每支酒按時序記錄配方演化、釀造實戰、品飲回饋,用 git 追蹤完整歷程。

## 📁 Repo 結構

```
homebrew-recipes/
├── README.md                          # 本檔案
├── crazy-concubine/                   # 妃子起笑 · Hazy Pale Ale
│   ├── README.md                      # 本支酒的迭代歷史與當前狀態
│   ├── v1-original.html               # 原始酒譜
│   ├── v2-neipa-evolution.html        # NEIPA 進化版(評估後未採用)
│   ├── v3-zero-cost.html              # 零成本優化路線
│   ├── v3.1-sop-hardening.html        # SOP 強化版
│   ├── v4-whirlpool-aroma.html        # 熱端香氣強化版(★ 目前最新,完整版)
│   └── brew-sheet.html                # 精簡列印版(實釀用,永遠對應最新版)
├── orange-glow/                       # Orange Glow · DDH NEIPA
│   ├── README.md
│   ├── v1-original.html               # 原始酒譜
│   ├── v2-lessons-learned.html        # 整合妃子起笑教訓
│   ├── v2.1-starter-fix-aldc.html     # Starter 修正 + ALDC 整合
│   ├── v2.2-whirlpool-fermaid.html    # 旋渦降溫 + Fermaid-O 為主
│   ├── v2.3-dme.html                  # DME 取代葡萄糖 + 燕麥減量
│   ├── v2.4-golden-promise.html       # Golden Promise 基麥 + LalBrew Pomona 酵母(★ 目前最新,完整版)
│   └── brew-sheet.html                # 精簡列印版(實釀用,永遠對應最新版)
├── strange-haze/                      # Strange Haze · Imperial Milkshake IPA
│   ├── README.md
│   ├── label.png                      # 酒標圖(藍莓星雲)
│   ├── v0-mango-passion-draft.html    # 芒果百香草稿(未採用)
│   ├── v1-blueberry-vanilla.html      # 藍莓香草版(★ 目前最新,完整版)
│   └── brew-sheet.html                # 精簡列印版(實釀用)
├── milkshake-ipa/                     # Milkshake IPA · 低殘糖版
│   ├── README.md
│   ├── v1-low-residual-sugar.html     # 低殘糖芒果百香(★ 目前最新,完整版)
│   └── brew-sheet.html                # 精簡列印版(實釀用)
└── shared/                            # 跨酒譜共通 SOP
    └── filtering-trub-sop.html        # 完整濾渣流程(hot/cold side)
```

## 🍻 酒譜清單

| 酒名 | 風格 | OG | ABV | 當前版本 |
|---|---|---|---|---|
| [妃子起笑](./crazy-concubine/) | Hazy Pale Ale | 1.052 | 4.8-5.2% | v4 |
| [Orange Glow](./orange-glow/) | DDH NEIPA | 1.075-1.078 | 7.7-8.1% | v2.4 |
| [Strange Haze](./strange-haze/) | Imperial Milkshake IPA | 1.072-1.076 | 7.5-8%（標 9%） | v1 |
| [Milkshake IPA](./milkshake-ipa/) | Milkshake IPA（低殘糖） | 1.058-1.062 | 5.5-6% | v1 |

## 🔑 共通核心 SOP(兩支酒都套用)

這些是踩過坑後累積的標準作業流程,適用於所有 hazy/NEIPA 風格家釀:

### 1. 單段 Dry Hop 卡進主發酵期
**動機:** 避免 hop creep 在發酵收尾時引爆,讓酵母在活躍期同步消化新生糖與雙乙醯。
**做法:** 主發酵 50-60% 完成時(比重 1.030-1.025 或 1.045-1.035 依 OG 而定)一次性投入全部 dry hop。

### 2. 綠燈確認 SOP
轉桶前必須**同時**滿足:
- 比重連續兩次間隔 2 天完全不動
- 強迫雙乙醯測試通過(取 50ml 樣本隔水加熱 60-65°C 浸泡 15-20 分鐘,聞無奶油爆米花味)

### 3. 省略 Cold Crash
DDH/hazy 不做 cold crash,避免酒花顆粒與酵母過度沉澱導致香氣稀薄與瓶間分層。

### 4. 虹吸轉桶 SOP(沒有壓力發酵桶的替代方案)
- Keg 預先 CO₂ 驅氧 3 次以上
- 從 keg 液體口接管入酒,從底部入避免濺射
- 虹吸管離桶底 2-3cm,留底不吸渣
- 轉完立刻加壓 10-12 PSI 並冷藏

### 5. 低壓慢飽和強制碳酸
- 2-4°C 下 10-12 PSI 靜置 5-7 天
- **禁止 30 PSI 猛搖速成法**(氣泡會粗)
- 飽和後降到 8-10 PSI 出酒

### 6. 最佳賞味期
- 一般 NEIPA:2-4 週
- DDH NEIPA:2-3 週(對氧化更敏感)

### 7. 完整濾渣流程 → [shared/filtering-trub-sop.html](./shared/filtering-trub-sop.html)
**核心:** 髒活在 hot side(不怕氧化)幹完,cold side(發酵後)溫柔處理不攪動。
- **Hot side:** whirlpool 聚渣 → 趁熱撈大渣 → 冷卻後細目虹吸入桶
- **Cold side:** 不 whirlpool、不攪、不搖(該沉的早沉好)→ 細目虹吸留底轉桶 → 浮動 dip tube 出酒

### 8. 投酵母前高壓純氧充氧(關鍵步驟)
**動機:** 純氧充氧(溶氧可達飽和 ~12+ ppm)遠高於搖桶充空氣(上限 ~8 ppm)。投酵母前打 60-90 秒高壓純氧,讓酵母在生長期合成固醇、長細胞膜、繁殖足夠世代——這是高 OG(1.07+)能用**「一包乾酵母」**就跑得動的關鍵,不必硬加包數或養 starter。
**做法:** 麥汁降到投酵母溫度後、投酵母前,用純氧鋼瓶 + 擴散石打 **60-90 秒**(10L 批量);搭配 Fermaid-O 養活力。之後**絕不再進氧**(發酵後氧氣是敵人)。

## 📚 命名規範

**檔案命名:** `v[版本號]-[簡短描述].html`(英文小寫、連字號分隔)
**Commit 規範:** Conventional Commits 中文版
- `feat`: 新增酒譜版本
- `fix`: 修正錯誤
- `docs`: 文件更新
- `chore`: 雜項

## 🛠️ 工作流程

每支酒的迭代節奏:

1. **設計版本**(例如 v4):基於前版實戰回饋,在新 branch 設計
2. **釀造實作**:跑完一批
3. **品飲評估**:填寫該酒的 README 中的「實戰追蹤」表
4. **決定下一版**:風味調整(v5)或 SOP 微調(v4.1)

## 🔗 相關資源

- [Hop Creep 原理參考(jackiebaifood blog)](https://jackiebaifood.blogspot.com/2024/09/dry-hoppinghop-creep.html)
- [Verdant IPA 酵母 spec sheet](https://www.lallemandbrewing.com/en/canada/brewers-corner/products/lalbrew-verdant-ipa/)

---

最後更新:2026/06/01
