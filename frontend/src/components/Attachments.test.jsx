/**
 * Opening and saving an attachment (components/Attachments.jsx).
 *
 * Nothing here checks how it looks. What is checked:
 *
 *  - Nothing is fetched until the user asks, and then one attachment at a time.
 *  - The file is fetched through the API client, never linked to: the token
 *    travels as a header, which <img src> and <a href> cannot send.
 *  - What the server sent decides how a file is shown. The backend serves a
 *    sender's HTML or SVG as an opaque download; if such a Blob ever reached
 *    View, it must not become a page.
 *  - A blob: URL does not outlive what it shows. A missing revoke keeps email
 *    content alive in the tab, and it is invisible on screen, so the calls are
 *    asserted directly.
 *
 * jsdom has no blob: URLs, so URL.createObjectURL and revokeObjectURL are
 * stubbed here, which is also what lets the tests see every call to them. Its
 * Blob also lacks text(), which every browser has, so that is filled in below
 * from FileReader.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Attachments from "./Attachments.jsx";
import * as api from "../api/client.js";

vi.mock("../api/client.js", () => ({
  fetchAttachment: vi.fn(),
}));

const PDF = { filename: "brief.pdf", content_type: "application/pdf", size: 5009 };
const IMAGE = { filename: "image.png", content_type: "image/png", size: 2216625 };
const NOTES = { filename: "notes.txt", content_type: "text/plain", size: 23 };
const ZIP = { filename: "bundle.zip", content_type: "application/zip", size: 4096 };
const PAGE = { filename: "invoice.html", content_type: "text/html", size: 900 };
const SVG = { filename: "logo.svg", content_type: "image/svg+xml", size: 700 };
const FORWARDED = { filename: "", content_type: "message/rfc822", size: 2048 };

if (typeof Blob.prototype.text !== "function") {
  Blob.prototype.text = function text() {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(this);
    });
  };
}

const blobOf = (type, content = "bytes") => new Blob([content], { type });

/** A promise the test settles by hand, to hold a fetch in flight. */
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

let created;
let clicks;

beforeEach(() => {
  vi.clearAllMocks();
  created = [];
  URL.createObjectURL = vi.fn(() => {
    created.push(`blob:mock/${created.length}`);
    return created[created.length - 1];
  });
  URL.revokeObjectURL = vi.fn();
  // The download is a click on a temporary <a download>. jsdom would treat it
  // as a navigation it cannot perform, so the click is recorded instead.
  clicks = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function click() {
    clicks.push({ href: this.getAttribute("href"), download: this.getAttribute("download") });
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function renderList(attachments, emailId = "email-1") {
  return render(<Attachments emailId={emailId} attachments={attachments} />);
}

const viewButton = (name) => screen.getByRole("button", { name: `View ${name}` });
const saveButton = (name) => screen.getByRole("button", { name: `Save ${name}` });

describe("the list", () => {
  it("renders nothing for an email without attachments", () => {
    for (const none of [[], undefined, null]) {
      const { container, unmount } = renderList(none);
      expect(container).toBeEmptyDOMElement();
      unmount();
    }
  });

  it("fetches nothing to render, however many attachments there are", () => {
    renderList([PDF, IMAGE, NOTES, ZIP, FORWARDED]);
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    expect(api.fetchAttachment).not.toHaveBeenCalled();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("offers View for images, PDFs and plain text, and for nothing else", () => {
    renderList([PDF, IMAGE, NOTES, ZIP, PAGE, SVG, FORWARDED]);
    const viewable = screen.getAllByRole("button", { name: /^view /i }).map((b) => b.getAttribute("aria-label"));
    expect(viewable).toEqual(["View brief.pdf", "View image.png", "View notes.txt"]);
  });

  it("offers Save for every attachment, including one the sender left unnamed", () => {
    renderList([PDF, ZIP, PAGE, SVG, FORWARDED]);
    expect(screen.getAllByRole("button", { name: /^save /i })).toHaveLength(5);
    expect(saveButton("Forwarded message")).toBeInTheDocument();
  });

  it("links to nothing: a link could not carry the token", () => {
    renderList([PDF, IMAGE]);
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });
});

describe("View", () => {
  it("fetches that one attachment, by the email and its place in the list", async () => {
    const user = userEvent.setup();
    api.fetchAttachment.mockResolvedValue(blobOf("image/png"));
    renderList([PDF, IMAGE], "email-7");

    await user.click(viewButton("image.png"));

    expect(api.fetchAttachment).toHaveBeenCalledTimes(1);
    expect(api.fetchAttachment.mock.calls[0].slice(0, 2)).toEqual(["email-7", 1]);
  });

  it("shows an image from a blob: URL, not from the API path", async () => {
    const user = userEvent.setup();
    api.fetchAttachment.mockResolvedValue(blobOf("image/png"));
    renderList([IMAGE]);

    await user.click(viewButton("image.png"));

    const image = await screen.findByRole("img", { name: "image.png" });
    expect(image.getAttribute("src")).toBe(created[0]);
    expect(image.getAttribute("src")).toMatch(/^blob:/);
  });

  it("shows a PDF in a frame that is not sandboxed", async () => {
    /* Regression. sandbox="" stops the browser's own PDF viewer from running,
       and the frame showed a broken-file icon instead of the document. */
    const user = userEvent.setup();
    api.fetchAttachment.mockResolvedValue(blobOf("application/pdf"));
    const { container } = renderList([PDF]);

    await user.click(viewButton("brief.pdf"));

    await screen.findByRole("region", { name: "Preview of brief.pdf" });
    const frame = container.querySelector("iframe");
    expect(frame.getAttribute("title")).toBe("brief.pdf");
    expect(frame.getAttribute("src")).toBe(created[0]);
    expect(frame.hasAttribute("sandbox")).toBe(false);
  });

  it("shows a text file as text, and makes no blob: URL for it", async () => {
    const user = userEvent.setup();
    api.fetchAttachment.mockResolvedValue(blobOf("text/plain", "Week 3: bring the <b>rubric</b>."));
    renderList([NOTES]);

    await user.click(viewButton("notes.txt"));

    const region = await screen.findByRole("region", { name: "Preview of notes.txt" });
    // As characters, never as markup.
    expect(within(region).getByText("Week 3: bring the <b>rubric</b>.")).toBeInTheDocument();
    expect(region.querySelector("b")).toBeNull();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("shows only the start of a very long text file, and says so", async () => {
    const user = userEvent.setup();
    api.fetchAttachment.mockResolvedValue(blobOf("text/plain", "x".repeat(20001)));
    renderList([NOTES]);

    await user.click(viewButton("notes.txt"));

    const region = await screen.findByRole("region", { name: "Preview of notes.txt" });
    expect(region.querySelector("pre").textContent).toHaveLength(20000);
    expect(within(region).getByText(/only the start of this file/i)).toBeInTheDocument();
  });

  it("does not render a file the server sent as an opaque download", async () => {
    /* The list said application/pdf; the server, which decides, sent
       octet-stream. Whatever the reason, it must not be framed. */
    const user = userEvent.setup();
    api.fetchAttachment.mockResolvedValue(blobOf("application/octet-stream", "<script>steal()</script>"));
    const { container } = renderList([PDF]);

    await user.click(viewButton("brief.pdf"));

    expect(await screen.findByRole("alert")).toHaveTextContent(/cannot be shown here/i);
    expect(container.querySelector("iframe, img, pre")).toBeNull();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("never frames HTML, even if the server labelled a file as such", async () => {
    const user = userEvent.setup();
    api.fetchAttachment.mockResolvedValue(blobOf("text/html", "<script>steal()</script>"));
    const { container } = renderList([PDF]);

    await user.click(viewButton("brief.pdf"));

    expect(await screen.findByRole("alert")).toHaveTextContent(/cannot be shown here/i);
    expect(container.querySelector("iframe, img, pre")).toBeNull();
  });

  it("says what went wrong, and for which file, when the fetch fails", async () => {
    const user = userEvent.setup();
    api.fetchAttachment.mockRejectedValue(new Error("Could not reach the server. Is the backend running?"));
    renderList([PDF]);

    await user.click(viewButton("brief.pdf"));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("brief.pdf");
    expect(alert).toHaveTextContent(/could not reach the server/i);
    expect(screen.queryByRole("region")).toBeNull();
  });

  it("offers a PDF in a new tab from the blob, never from the API path", async () => {
    /* A new tab cannot send the Authorization header any more than <img> can. */
    const user = userEvent.setup();
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    api.fetchAttachment.mockResolvedValue(blobOf("application/pdf"));
    renderList([PDF]);

    await user.click(viewButton("brief.pdf"));
    await user.click(await screen.findByRole("button", { name: /open it in a new tab/i }));

    expect(open).toHaveBeenCalledWith(created[0], "_blank", "noopener");
  });
});

describe("one fetch at a time", () => {
  it("ignores a second click while the first is still in flight", async () => {
    const user = userEvent.setup();
    const first = deferred();
    api.fetchAttachment.mockReturnValueOnce(first.promise);
    renderList([PDF, IMAGE]);

    await user.click(viewButton("brief.pdf"));
    await user.click(viewButton("image.png"));
    await user.click(saveButton("image.png"));
    expect(api.fetchAttachment).toHaveBeenCalledTimes(1);

    first.resolve(blobOf("application/pdf"));
    expect(await screen.findByRole("region", { name: "Preview of brief.pdf" })).toBeInTheDocument();
  });

  it("keeps the pressed button focused while it waits", async () => {
    /* Disabling a focused button drops focus to the page. The buttons are
       marked busy instead, and the click handler does the refusing. */
    const user = userEvent.setup();
    const first = deferred();
    api.fetchAttachment.mockReturnValueOnce(first.promise);
    renderList([PDF]);

    await user.click(viewButton("brief.pdf"));

    expect(viewButton("brief.pdf")).toHaveFocus();
    expect(viewButton("brief.pdf")).not.toBeDisabled();
    expect(viewButton("brief.pdf")).toHaveAttribute("aria-disabled", "true");
    first.resolve(blobOf("application/pdf"));
    await screen.findByRole("region", { name: "Preview of brief.pdf" });
    expect(screen.getByRole("button", { name: "Hide brief.pdf" })).not.toHaveAttribute("aria-disabled");
  });
});

describe("a blob: URL does not outlive what it shows", () => {
  it("is revoked when the preview is hidden", async () => {
    const user = userEvent.setup();
    api.fetchAttachment.mockResolvedValue(blobOf("application/pdf"));
    renderList([PDF]);

    await user.click(viewButton("brief.pdf"));
    await screen.findByRole("region", { name: "Preview of brief.pdf" });
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Hide brief.pdf" }));

    expect(URL.revokeObjectURL).toHaveBeenCalledWith(created[0]);
    expect(screen.queryByRole("region")).toBeNull();
  });

  it("is revoked when the preview's own close button is pressed", async () => {
    const user = userEvent.setup();
    api.fetchAttachment.mockResolvedValue(blobOf("image/png"));
    renderList([IMAGE]);

    await user.click(viewButton("image.png"));
    await user.click(await screen.findByRole("button", { name: "Close the preview of image.png" }));

    expect(URL.revokeObjectURL).toHaveBeenCalledWith(created[0]);
    expect(screen.queryByRole("region")).toBeNull();
  });

  it("is revoked when another attachment takes its place", async () => {
    const user = userEvent.setup();
    api.fetchAttachment
      .mockResolvedValueOnce(blobOf("application/pdf"))
      .mockResolvedValueOnce(blobOf("image/png"));
    renderList([PDF, IMAGE]);

    await user.click(viewButton("brief.pdf"));
    await screen.findByRole("region", { name: "Preview of brief.pdf" });
    await user.click(viewButton("image.png"));
    await screen.findByRole("region", { name: "Preview of image.png" });

    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(created[0]);
    expect(screen.getByRole("img", { name: "image.png" }).getAttribute("src")).toBe(created[1]);
  });

  it("is revoked when the pane goes away", async () => {
    const user = userEvent.setup();
    api.fetchAttachment.mockResolvedValue(blobOf("application/pdf"));
    const { unmount } = renderList([PDF]);

    await user.click(viewButton("brief.pdf"));
    await screen.findByRole("region", { name: "Preview of brief.pdf" });
    unmount();

    expect(URL.revokeObjectURL).toHaveBeenCalledWith(created[0]);
  });

  it("is revoked, and the preview closed, when a different email is opened", async () => {
    const user = userEvent.setup();
    api.fetchAttachment.mockResolvedValue(blobOf("application/pdf"));
    const { rerender } = renderList([PDF], "email-1");

    await user.click(viewButton("brief.pdf"));
    await screen.findByRole("region", { name: "Preview of brief.pdf" });
    rerender(<Attachments emailId="email-2" attachments={[IMAGE]} />);

    expect(URL.revokeObjectURL).toHaveBeenCalledWith(created[0]);
    await waitFor(() => expect(screen.queryByRole("region")).toBeNull());
  });

  it("an attachment that arrives after its email was closed is dropped", async () => {
    const user = userEvent.setup();
    const slow = deferred();
    api.fetchAttachment.mockReturnValueOnce(slow.promise);
    const { rerender } = renderList([PDF], "email-1");

    await user.click(viewButton("brief.pdf"));
    const signal = api.fetchAttachment.mock.calls[0][2].signal;
    rerender(<Attachments emailId="email-2" attachments={[IMAGE]} />);
    expect(signal.aborted).toBe(true);

    slow.resolve(blobOf("application/pdf"));
    await waitFor(() => expect(viewButton("image.png")).not.toHaveAttribute("aria-disabled"));
    expect(screen.queryByRole("region")).toBeNull();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});

describe("Save", () => {
  it("downloads the file under its own name, from a blob: URL", async () => {
    const user = userEvent.setup();
    api.fetchAttachment.mockResolvedValue(blobOf("application/octet-stream"));
    renderList([PDF, ZIP], "email-9");

    await user.click(saveButton("bundle.zip"));

    await waitFor(() => expect(clicks).toHaveLength(1));
    expect(api.fetchAttachment.mock.calls[0].slice(0, 2)).toEqual(["email-9", 1]);
    expect(clicks[0]).toEqual({ href: created[0], download: "bundle.zip" });
  });

  it("revokes the URL once the browser has the file, and leaves no link behind", async () => {
    const user = userEvent.setup();
    api.fetchAttachment.mockResolvedValue(blobOf("application/octet-stream"));
    renderList([ZIP]);

    await user.click(saveButton("bundle.zip"));

    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith(created[0]));
    expect(document.querySelector("a[download]")).toBeNull();
  });

  it("gives a forwarded email a name a mail client can open", async () => {
    const user = userEvent.setup();
    api.fetchAttachment.mockResolvedValue(blobOf("application/octet-stream"));
    renderList([FORWARDED]);

    await user.click(saveButton("Forwarded message"));

    await waitFor(() => expect(clicks).toHaveLength(1));
    expect(clicks[0].download).toBe("forwarded-message.eml");
  });

  it("saves a file it will not show: an attached web page stays a download", async () => {
    const user = userEvent.setup();
    api.fetchAttachment.mockResolvedValue(blobOf("application/octet-stream", "<script>steal()</script>"));
    const { container } = renderList([PAGE]);

    await user.click(saveButton("invoice.html"));

    await waitFor(() => expect(clicks).toHaveLength(1));
    expect(clicks[0].download).toBe("invoice.html");
    expect(container.querySelector("iframe, img, pre")).toBeNull();
  });

  it("does not disturb a preview that is open", async () => {
    const user = userEvent.setup();
    api.fetchAttachment
      .mockResolvedValueOnce(blobOf("application/pdf"))
      .mockResolvedValueOnce(blobOf("application/pdf"));
    renderList([PDF]);

    await user.click(viewButton("brief.pdf"));
    await screen.findByRole("region", { name: "Preview of brief.pdf" });
    await user.click(saveButton("brief.pdf"));
    await waitFor(() => expect(clicks).toHaveLength(1));

    expect(screen.getByRole("region", { name: "Preview of brief.pdf" })).toBeInTheDocument();
    // The download's URL was revoked; the preview's was not.
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(created[1]);
  });

  it("reports a failed download instead of saving nothing silently", async () => {
    const user = userEvent.setup();
    api.fetchAttachment.mockRejectedValue(new Error("That attachment could not be found on this email."));
    renderList([ZIP]);

    await user.click(saveButton("bundle.zip"));

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be found/i);
    expect(clicks).toHaveLength(0);
  });
});
