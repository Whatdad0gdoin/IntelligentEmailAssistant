/**
 * Auto-Categorise view (FR-02). Calls POST /api/classify.
 *
 * One batch call for the whole inbox, not one per row: that is what the
 * endpoint is shaped for and what keeps this inside the latency budget
 * (NFR-01).
 *
 * The fifth bucket matters here. The classifier can only return one of four
 * labels; "Review" is what the UI does with a label whose evidence span did not
 * check out or whose confidence fell short. Section 4.3 -- an unverified label
 * is not quietly downgraded to a guess, it is routed somewhere a human looks.
 *
 * Response: { results: [{ id, category, confidence, ... }] }
 */

import { useEffect, useRef, useState } from "react";
import { ChevronRight, ListChecks } from "lucide-react";

import * as api from "../api/client.js";
import { API_TO_KEY, CATEGORIES, REVIEW_CATEGORY } from "../lib/constants.js";

const ALL_BUCKETS = [...CATEGORIES, REVIEW_CATEGORY];

export default function Categorise({ emails, onBack }) {
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const abortRef = useRef(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const run = async () => {
    if (loading) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);
    try {
      const payload = await api.classify(
        emails.map((e) => ({ id: e.apiId, subject: e.subject, body: e.body })),
        { signal: controller.signal }
      );
      setResults(payload.results);
    } catch (err) {
      if (err.name !== "AbortError") setError(err.message);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  };

  // Group by the label that came back. A result the backend routed to Review
  // arrives with category "Review" already set, so nothing is re-decided here.
  const byBucket = {};
  for (const bucket of ALL_BUCKETS) byBucket[bucket.key] = [];
  for (const r of results ?? []) {
    const key = API_TO_KEY[r.category] ?? REVIEW_CATEGORY.key;
    const email = emails.find((e) => e.apiId === r.id);
    if (email) byBucket[key].push({ email, result: r });
  }

  return (
    <div className="feature-wrap">
      <div className="soon-crumb">
        <button onClick={onBack}>Inbox</button>
        <ChevronRight size={14} />
        <span>Auto-Categorise</span>
      </div>

      <header className="feature-head">
        <div className="feature-icon"><ListChecks size={22} strokeWidth={2.2} /></div>
        <div>
          <h1 className="main-title">Auto-Categorise</h1>
          <p className="main-sub">
            Sort the inbox into Work, Personal, Promotions and Studies. Anything the
            classifier could not evidence goes to Review.
          </p>
        </div>
      </header>

      <button className="primary-btn" onClick={run} disabled={loading}>
        {loading
          ? <><span className="spinner sm" /> Classifying {emails.length} emails…</>
          : <><ListChecks size={15} strokeWidth={2.2} /> Classify inbox ({emails.length})</>}
      </button>

      {error && <div className="feature-error"><b>Could not classify.</b><span>{error}</span></div>}

      {results && (
        <div className="bucket-grid">
          {ALL_BUCKETS.map((bucket) => (
            <section className="bucket" key={bucket.key} style={{ "--c": bucket.color }}>
              <h3 className="bucket-head">
                <span className="cat-dot" /> {bucket.label}
                <span className="chip-count">{byBucket[bucket.key].length}</span>
              </h3>
              {bucket.key === REVIEW_CATEGORY.key && byBucket[bucket.key].length > 0 && (
                <p className="bucket-note">{REVIEW_CATEGORY.explanation} — confirm these yourself.</p>
              )}
              {byBucket[bucket.key].length === 0 ? (
                <p className="bucket-empty">Nothing here.</p>
              ) : (
                <ul className="bucket-list">
                  {byBucket[bucket.key].map(({ email, result }) => (
                    <li key={email.id}>
                      <span className="bucket-subject">{email.subject}</span>
                      <span className="bucket-from">{email.from}</span>
                      <span className="bucket-conf">{Math.round((result.confidence ?? 0) * 100)}% confidence</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
