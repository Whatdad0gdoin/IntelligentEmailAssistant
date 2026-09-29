/**
 * Test environment setup, loaded before every test file.
 *
 * Two things only:
 *
 *  - jest-dom's matchers, so an assertion can say what it means
 *    (toBeInTheDocument, toBeDisabled) instead of poking at DOM internals.
 *  - an unmount after each test. Testing Library registers this itself when
 *    Vitest runs with `globals: true`; this project does not, so leaking a
 *    mounted tree into the next test is the default unless we clean up here.
 */

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
