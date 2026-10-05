import { makerCatalog } from './maker';

/** Demo scope only: accessories and image-only motors are not electronics to verify. */
export const demoHardware = ['raspberry-pi-5', 'hc-sr04', 'mrd-tf240-8p-cs'] as const;
export type DemoHardwareId = typeof demoHardware[number];
export type PurchasedHardware = Record<DemoHardwareId, string>;
export const emptyPurchasedHardware = (): PurchasedHardware => ({ 'raspberry-pi-5': '', 'hc-sr04': '', 'mrd-tf240-8p-cs': '' });

export function hardwarePartsCheckPrompt(purchased: PurchasedHardware, locale: string, includePhoto: boolean): string {
  const en = locale === 'en';
  const missing = en ? 'Not provided; cannot confirm.' : '未提供，無法確認。';
  const expected = (id: DemoHardwareId) => id === 'raspberry-pi-5' ? 'Raspberry Pi 5'
    : makerCatalog.modules.find(module => module.id === id)!.variant;
  const evidence = demoHardware.map((id, index) => `${index + 1}. ${expected(id)}\n   ${en ? 'I bought' : '我買的'}：${purchased[id].trim() || missing}`);
  return (en
    ? 'Check only the broad hardware types: a Pi 5-like controller board, an ultrasonic module and a TFT screen. Similar appearance and purpose count as Right part; exact model, RAM, voltage and controller variants are not acceptance requirements for this step. Reply with exactly three short bullets, one per item: **part: Right part / Wrong part / Cannot confirm**. For Right part, add no explanation. Wrong part is only for a clearly different hardware type; add a few words identifying the difference. Cannot confirm is only when the hardware type is not visible; name the view to photograph. No table, introduction, conclusion or repeated caveats. This is type recognition, not compatibility verification, redesign or wiring confirmation.\n\n'
    : '這一關只核對零件類型：Pi 5 類控制板、超音波模組、TFT 螢幕。外觀與用途接近就說買對；不要求完整型號、RAM、供電版本或控制晶片完全相同。只回覆三個短條列：**零件：買對／買錯／還不能確認**。買對不用解釋。明顯是不同零件類型才說買錯，附幾個字說明差異。只有看不清零件類型才說還不能確認，指出要補拍的角度。不用表格、開場、總結或重複提醒。這是類型辨識，不是相容性驗證、重新設計或接線完成確認。\n\n')
    + evidence.join('\n\n') + '\n\n' + (includePhoto
      ? (en ? 'Use only the explicitly selected current conversation photo.' : '僅使用我勾選的目前對話照片。')
      : (en ? 'No photo is supplied with this request. Do not infer visible hardware from older messages.' : '這次沒有附照片；不要從舊對話推測實物。'));
}
