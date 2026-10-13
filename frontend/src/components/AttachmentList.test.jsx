/**
 * Attachment rendering: what the list claims, and how a file gets opened.
 *
 * Nothing here checks how it looks. What is checked is:
 *
 *  - An attachment whose text could not be read says so, because the summary
 *    above it is then missing that content. A row showing only a filename
 *    implies the assistant used the file.
 *  - Nothing is fetched on render. Opening is a click, so a message with ten
 *    attachments costs nothing until the user asks for one.
 *  - Preview is offered only for types the backend will serve inline. A
 *    .docx or a .zip is download-only, and so is anything the browser would
 *    execute as markup.
 *  - Object URLs are revoked, so email content does not outlive the row.
 *
 * jsdom has no real blob plumbing, so URL.createObjectURL and revokeObjectURL
 * are stubbed and asserted on directly. That is the point of these tests
 * rather than a limitation of them: the leak this guards against is a missing
 * revoke call, which is exactly what a spy can see and a rendered pixel
 * cannot.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AttachmentList from "./AttachmentList.jsx";
import * as api from "../api/client.js";

vi.mock("../api/client.js", () => ({
  fetchAttachment: vi.fn(),
}));

const PDF = {
  id: "att-pdf", filename: "invoice-NG-2291.pdf", content_type: "application/pdf",
  size_bytes: 24_000, status: "extracted", has_text: true, truncated: false,
  can_open: true, can_preview: true, detail: "",
};

const SCAN = {
  id: "att-scan", filename: "scanned-letter.pdf", content_type: "application/pdf",
  size_bytes: 180_000, status: "empty", has_text: false, truncated: false,
  can_open: true, can_preview: true,
  detail: "This PDF has no text layer -- it is most likely a scan.",
};

const IMAGE = {
  id: "att-img", filename: "whiteboard.png", content_type: "image/png",
  size_bytes: 512_000, status: "image", has_text: false, truncated: false,
  can_open: true, can_preview: true, detail: "",
};

const ZIP = {
  id: "att-zip", filename: "bundle.zip", content_type: "application/zip",
  size_bytes: 2_000_000, status: "unsupported", has_text: false, truncated: false,
  can_open: true, can_preview: false, detail: "application/zip cannot be read.",
};

let created;

beforeEach(() => {
  vi.clearAllMocks();
  created = [];
  URL.createObjectURL = vi.fn(() => {
    const url = `blob:mock/${created.length}`;
    created.push(url);
    return url;
  });
  URL.revokeObjectURL = vi.fn();
  api.fetchAttachment.mockResolvedValue(
    new Blob(["bytes"], { type: "application/pdf" })
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("what the list says about each file", () => {
  it("renders nothing at all when there are no attachments", () => {
    const { container } = render(<AttachmentList attachments={[]} emailId="e1" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("names every attached file", () => {
    render(<AttachmentList attachments={[PDF, SCAN, IMAGE]} emailId="e1" />);
    expect(screen.getByText("invoice-NG-2291.pdf")).toBeInTheDocument();
    expect(screen.getByText("scanned-letter.pdf")).toBeInTheDocument();
    expect(screen.getByText("whiteboard.png")).toBeInTheDocument();
  });

  it("says when a file's text was actually read", () => {
    render(<AttachmentList attachments={[PDF]} emailId="e1" />);
    expect(screen.getByText(/text read/i)).toBeInTheDocument();
  });

  it("says why an unreadable file was not read, rather than staying silent", () => {
    /* The failure this guards: a scanned invoice listed by name only, with a
       summary above that never mentions it. Matched on "no text layer"
       rather than "scan", which would also hit the filename. */
    render(<AttachmentList attachments={[SCAN]} emailId="e1" />);
    expect(screen.getByText(/no text layer/i)).toBeInTheDocument();
  });

  it("tells the reader an image is there to be opened, not described", () => {
    render(<AttachmentList attachments={[IMAGE]} emailId="e1" />);
    expect(screen.getByText(/open to view/i)).toBeInTheDocument();
  });

  it("warns up front how many attachments the summary left out", () => {
    render(<AttachmentList attachments={[PDF, SCAN, IMAGE]} emailId="e1" />);
    expect(screen.getByText(/2 not included in the summary/i)).toBeInTheDocument();
  });

  it("raises no warning when everything was read", () => {
    render(<AttachmentList attachments={[PDF]} emailId="e1" />);
    expect(screen.queryByText(/not included in the summary/i)).not.toBeInTheDocument();
  });

  it("reports sizes in units a person reads", () => {
    render(<AttachmentList attachments={[PDF, IMAGE, ZIP]} emailId="e1" />);
    expect(screen.getByText("23 KB")).toBeInTheDocument();   // 24,000 bytes
    expect(screen.getByText("500 KB")).toBeInTheDocument();  // 512,000 bytes
    expect(screen.getByText("1.9 MB")).toBeInTheDocument();  // 2,000,000 bytes
  });
});

describe("the cost of rendering", () => {
  it("fetches nothing on render, however many attachments there are", () => {
    const many = [1, 2, 3, 4, 5].map((n) => ({ ...IMAGE, id: `img-${n}` }));
    render(<AttachmentList attachments={many} emailId="e1" />);
    expect(api.fetchAttachment).not.toHaveBeenCalled();
  });

  it("offers no analysis of any kind, because nothing interprets a picture", () => {
    render(<AttachmentList attachments={[IMAGE]} emailId="e1" />);
    expect(screen.queryByRole("button", { name: /analyse|describe/i })).not.toBeInTheDocument();
  });
});

describe("what can be opened and how", () => {
  it("offers View only for types the backend will serve inline", () => {
    render(<AttachmentList attachments={[PDF, ZIP]} emailId="e1" />);
    expect(screen.getAllByRole("button", { name: /view/i })).toHaveLength(1);
  });

  it("offers Save for a file it will not preview", () => {
    render(<AttachmentList attachments={[ZIP]} emailId="e1" />);
    expect(screen.queryByRole("button", { name: /view/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /download bundle\.zip/i })).toBeInTheDocument();
  });

  it("offers nothing to open when there are no bytes to hand back", () => {
    const gone = { ...PDF, id: "big", status: "too_large",
                   can_open: false, can_preview: false };
    render(<AttachmentList attachments={[gone]} emailId="e1" />);
    expect(screen.queryByRole("button", { name: /view/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /download/i })).not.toBeInTheDocument();
    expect(screen.getByText(/too large/i)).toBeInTheDocument();
  });

  it("fetches through the api client, with the email and attachment ids", async () => {
    const user = userEvent.setup();
    render(<AttachmentList attachments={[PDF]} emailId="email-7" />);

    await user.click(screen.getByRole("button", { name: /view/i }));

    expect(api.fetchAttachment).toHaveBeenCalledWith("email-7", "att-pdf");
  });

  it("renders a PDF in a frame pointed at a blob URL", async () => {
    const user = userEvent.setup();
    const { container } = render(<AttachmentList attachments={[PDF]} emailId="e1" />);

    await user.click(screen.getByRole("button", { name: /view/i }));

    const frame = await waitFor(() => {
      const found = container.querySelector("iframe");
      expect(found).not.toBeNull();
      return found;
    });
    expect(frame.getAttribute("src")).toMatch(/^blob:/);
    expect(frame.getAttribute("title")).toBe("invoice-NG-2291.pdf");
  });

  it("does not sandbox the PDF frame, because that stops it rendering", async () => {
    /* Regression. sandbox="" revokes every permission, and the browser's own
       PDF viewer is a scripted same-origin application that will not start
       without them -- the frame rendered a broken-file icon. The containment
       here is that only application/pdf can ever reach this frame, plus the
       viewer's own process sandbox. */
    const user = userEvent.setup();
    const { container } = render(<AttachmentList attachments={[PDF]} emailId="e1" />);

    await user.click(screen.getByRole("button", { name: /view/i }));

    const frame = await waitFor(() => {
      const found = container.querySelector("iframe");
      expect(found).not.toBeNull();
      return found;
    });
    expect(frame.hasAttribute("sandbox")).toBe(false);
  });

  it("offers a way out when the frame will not render", async () => {
    const user = userEvent.setup();
    render(<AttachmentList attachments={[PDF]} emailId="e1" />);

    await user.click(screen.getByRole("button", { name: /view/i }));

    expect(await screen.findByRole("button", { name: /open in a new tab/i }))
      .toBeInTheDocument();
  });

  it("opens the new tab from the blob, never from the authenticated path", async () => {
    /* A new tab cannot carry the Authorization header, so pointing it at the
       API URL would render a 401 page. */
    const user = userEvent.setup();
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    render(<AttachmentList attachments={[PDF]} emailId="e1" />);

    await user.click(screen.getByRole("button", { name: /view/i }));
    await user.click(await screen.findByRole("button", { name: /open in a new tab/i }));

    expect(open).toHaveBeenCalledWith(created[0], "_blank", "noopener");
  });

  it("renders an image inline", async () => {
    const user = userEvent.setup();
    api.fetchAttachment.mockResolvedValue(new Blob(["x"], { type: "image/png" }));
    render(<AttachmentList attachments={[IMAGE]} emailId="e1" />);

    await user.click(screen.getByRole("button", { name: /view/i }));

    const img = await screen.findByAltText("whiteboard.png");
    expect(img.getAttribute("src")).toMatch(/^blob:/);
  });

  it("surfaces a failure instead of leaving the button spinning", async () => {
    const user = userEvent.setup();
    api.fetchAttachment.mockRejectedValue(new Error("Could not reach the server."));
    render(<AttachmentList attachments={[PDF]} emailId="e1" />);

    await user.click(screen.getByRole("button", { name: /view/i }));

    expect(await screen.findByText(/could not reach the server/i)).toBeInTheDocument();
  });
});

describe("object URLs do not outlive what they show", () => {
  it("revokes the preview URL when the preview is closed", async () => {
    const user = userEvent.setup();
    const { container } = render(<AttachmentList attachments={[PDF]} emailId="e1" />);

    await user.click(screen.getByRole("button", { name: /view/i }));
    await waitFor(() => expect(container.querySelector("iframe")).not.toBeNull());
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /hide/i }));

    expect(URL.revokeObjectURL).toHaveBeenCalledWith(created[0]);
    expect(container.querySelector("iframe")).toBeNull();
  });

  it("revokes the preview URL when the component unmounts", async () => {
    const user = userEvent.setup();
    const { container, unmount } = render(
      <AttachmentList attachments={[PDF]} emailId="e1" />
    );

    await user.click(screen.getByRole("button", { name: /view/i }));
    await waitFor(() => expect(container.querySelector("iframe")).not.toBeNull());
    unmount();

    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith(created[0]));
  });

  it("revokes the download URL once the browser has taken its copy", async () => {
    const user = userEvent.setup();
    render(<AttachmentList attachments={[ZIP]} emailId="e1" />);

    await user.click(screen.getByRole("button", { name: /download bundle\.zip/i }));

    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith(created[0]));
  });
});
