const http = require("http");
const fs = require("fs");
const path = require("path");

const PORT = process.env.PORT || 3000;
const ROOT = __dirname;

const MIME_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".svg": "image/svg+xml"
};

http
  .createServer((req, res) => {
    const reqUrl = new URL(req.url, `http://${req.headers.host}`);
    let pathname = reqUrl.pathname;

    if (pathname === "/") pathname = "/index.html";

    const safePath = path.normalize(path.join(ROOT, pathname));
    if (!safePath.startsWith(ROOT)) {
      res.writeHead(403);
      res.end("Forbidden");
      return;
    }

    fs.readFile(safePath, (err, data) => {
      if (err) {
        res.writeHead(err.code === "ENOENT" ? 404 : 500, {
          "Content-Type": "text/plain; charset=utf-8"
        });
        res.end(err.code === "ENOENT" ? "Not found" : "Server error");
        return;
      }

      const ext = path.extname(safePath).toLowerCase();
      res.writeHead(200, { "Content-Type": MIME_TYPES[ext] || "application/octet-stream" });
      res.end(data);
    });
  })
  .listen(PORT, () => {
    console.log(`Server running at http://localhost:${PORT}`);
  });
