/**
 * Settings view (section 5.5) -- NOT IMPLEMENTED YET. Built in step 7, once
 * capability detection exists to report browser voice support.
 *
 * Scope when built is deliberately narrow: voice on/off, browser capability
 * status, cache clear. The FIT3163 wireframe also showed default reply tone and
 * translation language; both belong to FR-06/FR-07, which are out of scope for
 * this build.
 */

import { Settings as SettingsIcon } from "lucide-react";

import ComingSoon from "../components/ComingSoon.jsx";

const FEATURE = {
  id: "settings",
  label: "Settings",
  icon: SettingsIcon,
  desc: "Voice on/off, browser capability status, and cache clear.",
};

export default function Settings({ onBack }) {
  return <ComingSoon feature={FEATURE} onBack={onBack} />;
}
