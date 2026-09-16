import { useState, type FormEvent } from "react";
import { postQuery } from "../lib/api";
import { useI18n } from "../lib/i18n";
import type { QueryResponse } from "../lib/types";

interface QueryBoxProps {
  result: QueryResponse | null;
  onResult: (result: QueryResponse) => void;
  onClear: () => void;
}

export function QueryBox({ result, onResult, onClear }: QueryBoxProps) {
  const { t, locale } = useI18n();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const question = text.trim();
    if (!question || busy) return;
    setBusy(true);
    setFailed(false);
    try {
      onResult(await postQuery(question, locale));
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="querybox"
      onSubmit={(event) => {
        void submit(event);
      }}
    >
      <div className="query-row">
        <input
          className="query-input"
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={t("query.placeholder")}
          spellCheck={false}
          aria-label={t("query.placeholder")}
        />
        <button className="query-send" type="submit" disabled={busy || text.trim() === ""}>
          {busy ? t("query.busy") : t("query.send")}
        </button>
      </div>
      {failed ? (
        <div className="query-result nomatch">
          <span className="query-answer">{t("query.failed")}</span>
          <button type="button" className="query-clear" onClick={() => setFailed(false)}>
            {t("query.clear")}
          </button>
        </div>
      ) : (
        result && (
          <div className={`query-result${result.matched ? "" : " nomatch"}`}>
            <span className="query-answer">{result.answer}</span>
            <button type="button" className="query-clear" onClick={onClear}>
              {t("query.clear")}
            </button>
          </div>
        )
      )}
    </form>
  );
}
