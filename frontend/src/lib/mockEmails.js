/**
 * PLACEHOLDER DATA -- replaced in step 4 by GET /api/inbox.
 *
 * These six emails are the teammate's original mock set, kept verbatim so the
 * inbox still renders while the backend routes are being built. They are the
 * only remaining hardcoded emails in the app.
 *
 * Two things to note before this file is deleted:
 *  - `cat` values here are hand-authored, NOT classifier output. Nothing in the
 *    UI should present them as a real FR-02 result.
 *  - `body` is shipped in the JS bundle. That is acceptable for placeholder
 *    fixtures but must not survive: real bodies come from the backend adapter
 *    per request and are never persisted (NFR-03).
 */

export const MOCK_EMAILS = [
  { id: 1, from: "Mr Robinson", email: "d.robinson@northgate.com.au", initials: "MR", subject: "Project deadline moved to Friday", preview: "Hi, can we reschedule our Thursday meeting to Friday at 2pm? I'd like to review the report together before…", cat: "work", time: "9:24 AM", unread: true, star: true, attach: true,
    body: "Hi,\n\nCan we reschedule our Thursday meeting to Friday at 2pm? I'd like to review the quarterly report together before it goes out to the wider team.\n\nI've attached the latest draft so you can take a look beforehand. Let me know if that time works for you.\n\nBest regards,\nDavid Robinson\nOperations Manager, Northgate" },
  { id: 2, from: "Monash Enrolments", email: "no-reply@monash.edu", initials: "ME", subject: "Semester 2 unit registration now open", preview: "Your registration window for Semester 2 has opened. Please complete your enrolment by the census date to…", cat: "studies", time: "8:10 AM", unread: true, star: false, attach: false,
    body: "Dear Student,\n\nYour registration window for Semester 2 has now opened. Please complete your enrolment by the census date to avoid late fees.\n\nYou can register for units through the student portal. If you have any questions about your course plan, please contact your faculty advisor.\n\nKind regards,\nMonash Enrolments Team" },
  { id: 3, from: "Sarah Chen", email: "sarah.chen.mel@gmail.com", initials: "SC", subject: "Dinner this weekend?", preview: "Hey! A few of us are getting together Saturday night. Would love for you to come along - let me know if…", cat: "personal", time: "Yesterday", unread: false, star: false, attach: false,
    body: "Hey!\n\nA few of us are getting together Saturday night for dinner at that new ramen place in the city. Would love for you to come along!\n\nWe're thinking around 7pm. Let me know if you can make it and I'll add you to the booking.\n\nTalk soon,\nSarah" },
  { id: 4, from: "TechDeals", email: "offers@techdeals-mail.com", initials: "TD", subject: "⚡ 48-hour flash sale - up to 60% off", preview: "Our biggest sale of the season is here. Grab premium gear at unbeatable prices before the clock runs out…", cat: "promo", time: "Yesterday", unread: true, star: false, attach: false,
    body: "Our biggest sale of the season is here!\n\nGrab premium gear at unbeatable prices before the clock runs out. Up to 60% off laptops, headphones, and accessories.\n\nThis offer ends in 48 hours. Shop now and don't miss out.\n\nUnsubscribe | Manage preferences" },
  { id: 5, from: "Dr Amelia Ford", email: "a.ford@monash.edu", initials: "AF", subject: "Feedback on your research proposal", preview: "I've reviewed your draft and left comments throughout. Overall a strong direction - a few points on the…", cat: "studies", time: "Mon", unread: false, star: true, attach: true,
    body: "Hi,\n\nI've reviewed your draft and left comments throughout the document. Overall it's a strong direction and I can see the project taking shape well.\n\nA few points on the methodology section need tightening, particularly around your evaluation metrics. Let's discuss these at our next supervision meeting.\n\nBest,\nDr Amelia Ford" },
  { id: 6, from: "GitHub", email: "noreply@github.com", initials: "GH", subject: "Security alert on ds-25/email-assistant", preview: "We detected a new sign-in to your account from a new device. If this was you, no action is needed…", cat: "work", time: "Mon", unread: false, star: false, attach: false,
    body: "Hi there,\n\nWe detected a new sign-in to your account from a new device. If this was you, no action is needed.\n\nIf you don't recognise this activity, please secure your account by changing your password immediately.\n\nThanks,\nThe GitHub Team" },
];
