import { NextRequest } from "next/server";
import crypto from "crypto";

function generateSignature(accountId: string, secret: string) {
  return crypto.createHmac("sha256", secret).update(accountId).digest("hex");
}

async function handleProxy(req: NextRequest, context: any) {
  const internalApiKey = process.env.INTERNAL_API_KEY || process.env.HMAC_KEY || "test_internal_key";
  const accountId = process.env.ACCOUNT_ID || "acc_demo_123";
  const apiBase = process.env.API_BASE || process.env.NEXT_PUBLIC_API_BASE || "http://web:8000";

  // Extract path parameters properly in Next.js App Router API routes
  const params = await context.params;
  const pathArray = params.path || [];
  const path = pathArray.join("/");
  const url = new URL(req.url);
  const targetUrl = `${apiBase}/${path}${url.search}`;

  if (!internalApiKey || !accountId) {
    return new Response(JSON.stringify({ error: "Server configuration missing API credentials" }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }

  const signature = generateSignature(accountId, internalApiKey);

  const headers = new Headers(req.headers);
  headers.delete("host");
  headers.delete("connection");
  // Attach our trusted tenant auth securely on the server
  headers.set("X-Account-ID", accountId);
  headers.set("X-Signature", signature);

  const options: RequestInit & { duplex?: string } = {
    method: req.method,
    headers,
  };

  if (req.method !== "GET" && req.method !== "HEAD") {
    options.body = req.body;
    options.duplex = 'half'; // required for passing request bodies in node fetch
  }

  try {
    const response = await fetch(targetUrl, options);
    
    // Pass the response headers back to the client
    const responseHeaders = new Headers(response.headers);
    
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders,
    });
  } catch (error: any) {
    console.error("Proxy error:", error);
    return new Response(JSON.stringify({ error: "Failed to fetch from backend" }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }
}

export const GET = handleProxy;
export const POST = handleProxy;
export const PUT = handleProxy;
export const PATCH = handleProxy;
export const DELETE = handleProxy;
