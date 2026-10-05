import type { Material } from './maker';

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
