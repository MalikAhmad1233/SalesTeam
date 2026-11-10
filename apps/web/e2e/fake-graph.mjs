// A stand-in for Meta's Graph API in local end-to-end runs (MIXT_WHATSAPP_GRAPH_BASE_URL points
// here). It accepts messages and lists one template; it never talks to Meta.
import { createServer } from "node:http";

const port = Number(process.env.FAKE_GRAPH_PORT ?? 8099);
let counter = 0;

const json = (res, status, body) => {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
};

createServer((req, res) => {
  const path = new URL(req.url ?? "/", "http://localhost").pathname;
  if (path === "/health") return json(res, 200, { ok: true });
  if (req.method === "POST" && /^\/v\d+\.\d+\/\d+\/messages$/.test(path)) {
    req.resume();
    counter += 1;
    return json(res, 200, { messaging_product: "whatsapp", messages: [{ id: `wamid.e2e${counter}` }] });
  }
  if (req.method === "GET" && /^\/v\d+\.\d+\/\d+\/message_templates$/.test(path)) {
    return json(res, 200, {
      data: [
        {
          id: "e2e-template-1",
          name: "trial_reminder",
          language: "en",
          status: "APPROVED",
          category: "UTILITY",
          components: [{ type: "BODY", text: "Hi {{1}}, your trial lesson is on {{2}}." }],
        },
      ],
      paging: { cursors: {} },
    });
  }
  if (req.method === "GET" && /^\/v\d+\.\d+\/\d+$/.test(path)) {
    return json(res, 200, { display_phone_number: "+971 4 312 3456", verified_name: "Mixt Academy (test)", quality_rating: "GREEN" });
  }
  return json(res, 404, { error: { message: "unknown path", code: 100 } });
}).listen(port, "127.0.0.1");
