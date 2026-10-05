// Isolated presentation fixture; no backend, AI, camera or hardware calls.
import { createRoot } from 'react-dom/client';
import { LocaleProvider } from '../src/lib/i18n';
import { AssistantMarkdown } from '../src/components/AssistantMarkdown';
import '../src/styles.css';
import '../src/maker.css';
import '../src/tinkro.css';
import '../src/debug.css';
import '../src/assistant.css';
import '../src/mobileWeb.css';

const options = new URLSearchParams(location.search);
document.documentElement.dataset.theme = options.get('theme') === 'light' ? 'light' : 'dark';
const mobile = options.get('surface') === 'mobile';
const text = `## 零件核對結果

僅依本次附上的三張照片與 **demo 規格** 比對：

| 零件 / demo 規格 | 判定 | 本次照片依據 | 缺少的規格 / 證據 | 下一個核對方式 |
|---|---|---|---|---|
| Raspberry Pi 5 | 符合（型號） | 照片可讀到 Raspberry Pi 5、16GB RAM，並可見 RP1 晶片。 | demo 未指定 RAM 容量；照片無法確認供電規格或功能正常。 | 對照購買標籤、包裝型號與原廠產品資料。 |
| HC-SR04+ / 3.3V 寬電壓版 | 疑似不同 | 照片標示 HC-SR04，未見「+」；可見 VCC、Trig、Echo、Gnd。 | 無法確認完整版本、3.3V 供電支援及 ECHO 是否為 3.3V 訊號。未見「+」也不足以斷定一定是標準 5V 版。 | 核對背面型號、包裝及該廠商的版本規格書，確認供電範圍與 ECHO 輸出電位。 |
| MRD_TFT240_8P_CS / ILI9341 / 240×320 | 無法確認（完整規格） | 照片可讀到 2.4 TFT LCD 240×320 RGB，以及 GND、VCC、SCL、SDA、RES、DC、CS、BLK 八針標示。 | 未見完整 MRD 型號、ILI9341 標示；控制器、SPI 介面、3.3V 供電相容性及 BLK 未接時的背光行為仍無法確認。 | 核對背面型號、產品標籤與對應版本規格書，逐項確認控制器、解析度、介面及供電。 |

### 下一步

1. 先查看 **超音波背面型號**。
2. 核對規格書中的供電與 ECHO 輸出。
   - 保留目前接線進度。
   - 尚未確認前，保持斷電。

> 照片只能提供外觀證據，不能確認導通或供電。

腳位標示 \`Pin 6\` 可與圖解引導交叉查看。

\`\`\`python
if specification_confirmed:
    print("查看規格 <不是執行硬體測試>")
\`\`\``;

const literal = '**我買的零件**：幫我核對，不要更改接線。';
const messages = <>
  <article className={mobile ? 'mw-message is-user' : 'ai-debug-message is-user'}>
    <header><strong>你</strong></header><p>{literal}</p>
  </article>
  <article className={mobile ? 'mw-message is-assistant' : 'ai-debug-message is-assistant'}>
    <header><strong>Tinkro AI</strong><small>排版驗證</small></header>
    <AssistantMarkdown text={text} />
  </article>
</>;

createRoot(document.getElementById('root')!).render(<LocaleProvider>
  {mobile ? <div className="mobile-web-app"><section className="mw-chat"><div className="mw-messages">{messages}</div></section></div>
    : <main className="app tinkro-theme markdown-preview"><section className="unified-assistant"><div className="unified-message-list">{messages}</div></section></main>}
</LocaleProvider>);
