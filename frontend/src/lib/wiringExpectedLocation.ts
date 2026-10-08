import pi5 from '../../../profiles/boards/raspberry-pi-5/board.json';
import { piHeaderLocation } from './piHeaderGuide';
import type { Pin } from './types';
import { wiringHasConnectionClue, type WiringReviewResult } from './wiringReview';
import type { WiringChatSummary } from './wiringChat';

type Translate = (zh: string, en: string) => string;
const pins = pi5.pins as unknown as Pin[];
const colours: Record<string, [string, string]> = {
  red: ['紅色', 'red'], orange: ['橘色', 'orange'], yellow: ['黃色', 'yellow'], green: ['綠色', 'green'],
  blue: ['藍色', 'blue'], purple: ['紫色', 'purple'], black: ['黑色', 'black'], white: ['白色', 'white'],
  brown: ['棕色', 'brown'], gray: ['灰色', 'gray'], grey: ['灰色', 'gray'], pink: ['粉紅色', 'pink'], teal: ['藍綠色', 'teal'],
};

/** Use the same J8 map and row helper as the guide. Never replace a saved target with today's wiring. */
export function expectedWiringLocation(row: WiringReviewResult) {
  const pin = pins.find(value => value.header === 'J8' && value.id === row.expected.board_pin && value.index === row.expected.physical_pin);
  const location = piHeaderLocation(pin);
  return pin && location ? { pin, ...location } : null;
}

export function wiringTargetLabel(row: WiringReviewResult, tr: Translate) {
  if (row.diagnosis?.kind === 'unconnected_terminal') return row.expected.component_pin;
  const colour = row.wire_colors?.component;
  return colour && colour.visibility !== 'not_visible' && colours[colour.name]
    ? tr(`${row.expected.component_pin}（${colours[colour.name][0]}線）`, `${row.expected.component_pin} (${colours[colour.name][1]} wire)`)
    : row.expected.component_pin;
}

export function wiringLocationTargets(rows: WiringReviewResult[], focusWireId?: string) {
  const first = rows.find(row => row.wire_id === focusWireId && expectedWiringLocation(row));
  if (!first) return [];
  if (first?.diagnosis?.kind === 'reciprocal_endpoint_swap') {
    const partner = rows.find(row => row.wire_id === first.diagnosis?.partner_wire_id && row.component_id === first.component_id && expectedWiringLocation(row));
    return partner ? [first, partner] : [first];
  }
  return [first];
}

/** Present saved evidence in plain language; keep the raw historical summary untouched. */
export function wiringVisualSummary(summary: WiringChatSummary, tr: Translate, focusWireId?: string): {
  headline: string; next_step: string; targets: WiringReviewResult[]; evidence?: string;
} {
  const locations = wiringLocationTargets(summary.results, focusWireId);
  const first = locations[0];
  const targets = first && wiringHasConnectionClue(first) ? locations : [];
  if (!first) return { headline: summary.headline, next_step: summary.next_step, targets };
  const finding = first.diagnosis;
  if (!summary.retake_role && finding?.status === 'suspected' && finding.kind === 'unconnected_terminal') return {
    targets, headline: tr(`${first.expected.component_pin} 這個腳位疑似漏接。`, `${first.expected.component_pin} may be unconnected.`),
    next_step: [finding.evidence, first.next_step || summary.next_step].filter(Boolean).join(' '),
  };
  if (summary.retake_role || summary.observation?.trim()) return { headline: summary.headline, next_step: summary.next_step, targets };
  if (finding?.status === 'uncertain' && finding.kind === 'row_position_check') return {
    targets, headline: summary.headline, next_step: summary.next_step, evidence: finding.evidence,
  };
  if (finding?.status === 'suspected' && finding.kind === 'reciprocal_endpoint_swap' && finding.partner_component_pin) {
    return { targets, headline: tr(`${first.expected.component_pin} 與 ${finding.partner_component_pin} 疑似接反。`, `${first.expected.component_pin} and ${finding.partner_component_pin} may be swapped.`),
      next_step: targets.length > 1 ? tr('查看應接位置，沿這兩條線分別核對。', 'View the intended connections and trace these two wires.')
        : tr(`查看應接位置，先沿 ${wiringTargetLabel(first, tr)} 核對。`, `View the intended connection and start by tracing ${wiringTargetLabel(first, tr)}.`) };
  }
  if (first.comparison === 'different' && finding?.status !== 'suspected') {
    const component = first.wire_colors?.component, board = first.wire_colors?.board;
    const reason = component && board && component.visibility !== 'not_visible' && board.visibility !== 'not_visible'
      && component.name !== board.name && colours[component.name] && colours[board.name]
      ? tr(`零件端是${colours[component.name][0]}線，Pi 應接位置看起來是${colours[board.name][0]}線。`, `The module wire is ${colours[component.name][1]}; the wire at the intended Pi position looks ${colours[board.name][1]}.`)
      : tr('照片中兩端線色不同。', 'The endpoint colours differ in the photos.');
    return { targets, headline: tr(`${wiringTargetLabel(first, tr)}疑似接錯，請先核對。`, `${wiringTargetLabel(first, tr)} may be connected incorrectly. Check it first.`),
      next_step: reason + tr('查看應接位置，再沿同一條線核對。', ' View the intended connection, then trace the same wire.') };
  }
  if (finding?.status === 'uncertain' && finding.module_identity_known && finding.module_attachment_uncertain
    && !finding.module_attachment_confirmed && !finding.retake_roles?.length
    && !first.component_candidates.some(candidate => candidate.contact === 'detached')) return {
    targets, headline: tr('照片尚未找出明確的接線疑點。', 'The photos have not identified a clear wiring concern.'),
    next_step: tr('可展開逐線核對，沿同一條線確認兩端。', 'Optionally open the wire-by-wire review and trace each wire between its endpoints.'),
  };
  return { targets, headline: summary.headline, next_step: summary.next_step };
}
