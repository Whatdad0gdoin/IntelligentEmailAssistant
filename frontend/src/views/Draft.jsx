/**
 * Draft view (FR-03) -- NOT IMPLEMENTED YET. Built in step 6.
 *
 * This is a placeholder so the route resolves. It must not pretend to work:
 * there is no textarea, no Approve control and no call to /api/draft here yet.
 */

import ComingSoon from "../components/ComingSoon.jsx";
import { FEATURES } from "../lib/constants.js";

export default function Draft({ onBack }) {
  const feature = FEATURES.find((f) => f.id === "reply");
  return <ComingSoon feature={feature} onBack={onBack} />;
}
