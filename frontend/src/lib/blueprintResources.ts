import type { Material } from './maker';

export type MaterialIllustrationKind = 'pi5' | 'ultrasonic' | 'tft' | 'jumper' | 'breadboard'
  | 'resistor' | 'power' | 'storage' | 'wheel' | 'axle' | 'standoff' | 'acrylic-panel' | 'bracket' | 'screw' | 'generic';

const materialArtById: Readonly<Record<string, MaterialIllustrationKind>> = {
  'raspberry-pi-5': 'pi5', 'hc-sr04': 'ultrasonic', 'mrd-tf240-8p-cs': 'tft',
  'jumper-wires': 'jumper', wires: 'jumper', breadboard: 'breadboard',
  resistors: 'resistor', 'power-supply': 'power', 'micro-sd': 'storage', 'sd-card': 'storage',
  wheel: 'wheel', axle: 'axle', standoff: 'standoff', 'acrylic-panel': 'acrylic-panel', bracket: 'bracket', screw: 'screw',
};

/** Decorative family illustrations only; never a model/voltage compatibility check. */
export function materialIllustrationKind(item: Pick<Material, 'id' | 'name'>): MaterialIllustrationKind {
  const id = item.id.toLowerCase().replace(/^structure-/, '');
  if (Object.hasOwn(materialArtById, id)) return materialArtById[id];
  const name = `${id} ${item.name}`.toLowerCase();
  if (/jumper|dupont|杜邦/.test(name)) return 'jumper';
  if (/breadboard|麵包板/.test(name)) return 'breadboard';
  if (/resistor|電阻/.test(name)) return 'resistor';
  if (/power.?supply|charger|電源|充電器/.test(name)) return 'power';
  if (/micro.?sd|sd.?card|記憶卡/.test(name)) return 'storage';
  if (/raspberry\s*pi\s*5|樹莓派\s*5/.test(name)) return 'pi5';
  if (/hc.?sr04|超音波/.test(name)) return 'ultrasonic';
  if (/mrd.?tf[t]?240|ili9341|tft/.test(name)) return 'tft';
  return 'generic';
}

/** Public catalogue/search links, never a checkout or a claim of compatibility. */
export function materialPurchaseLink(item: Pick<Material, 'id' | 'name'>) {
  if (item.id === 'raspberry-pi-5') return { url: 'https://www.raspberrypi.com/products/raspberry-pi-5/', official: true };
  const query = item.id === 'hc-sr04' ? 'HC-SR04+ 3.3V ECHO 3.3V'
    : item.id === 'mrd-tf240-8p-cs' ? 'MRD_TFT240_8P_CS ILI9341 2.4 inch 8 pin'
      : item.name;
  return { url: `https://www.google.com/search?tbm=shop&q=${encodeURIComponent(query)}`, official: false };
}

export function conciseMaterialName(name: string, locale: string) {
  const terms = name.split(' / ').map(term => term.trim()).filter(Boolean);
  return locale === 'en' ? terms.at(-1) ?? name : terms[0] ?? name;
}

export function assemblyActions(instruction: string) {
  return instruction.split(/(?<=[。；;])\s*/u).map(line => line.trim()).filter(Boolean);
}
