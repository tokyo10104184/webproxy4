import zipfile
import io
import os

# File contents definitions for Vercel deployment
package_json = """{
  "name": "advanced-web-proxy",
  "version": "2.0.0",
  "main": "api/index.js",
  "license": "MIT",
  "scripts": {
    "start": "node api/index.js"
  },
  "dependencies": {
    "axios": "^1.7.2",
    "express": "^4.19.2"
  }
}"""

vercel_json = """{
  "version": 2,
  "rewrites": [
    { "source": "/proxy", "destination": "/api/index.js" }
  ]
}"""

public_index_html = """<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Advanced Web Proxy</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <header>
        <h1>Web Proxy V2</h1>
        <form id="proxy-form">
            <input type="text" id="url-input" placeholder="https://example.com" required>
            <button type="submit">Go</button>
            <button type="button" id="copy-url-button" title="Copy URL">Copy</button>
            <button type="button" id="clear-all-button" title="Clear">Clear</button>
        </form>
    </header>
    <main>
        <!-- sandbox制限を緩和し、外部JSの実行を許可 -->
        <iframe id="content-frame" title="Proxy Content"></iframe>
    </main>
    <script src="script.js"></script>
</body>
</html>"""

public_style_css = """body, html {
    margin: 0;
    padding: 0;
    height: 100%;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    display: flex;
    flex-direction: column;
    background-color: #f4f4f4;
}

header {
    background-color: #2c3e50;
    padding: 15px;
    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
    display: flex;
    align-items: center;
    color: white;
    gap: 15px;
}

h1 {
    font-size: 1.2em;
    margin: 0;
    white-space: nowrap;
    font-weight: 600;
}

#proxy-form {
    flex-grow: 1;
    display: flex;
    gap: 8px;
}

#url-input {
    flex-grow: 1;
    padding: 10px;
    border: none;
    border-radius: 4px;
    font-size: 14px;
}

button {
    padding: 10px 16px;
    border: none;
    background-color: #3498db;
    color: white;
    border-radius: 4px;
    cursor: pointer;
    font-weight: bold;
    transition: background-color 0.2s;
}

button:hover {
    background-color: #2980b9;
}

#copy-url-button, #clear-all-button {
    background-color: #7f8c8d;
}

#copy-url-button:hover, #clear-all-button:hover {
    background-color: #626e70;
}

main {
    flex-grow: 1;
    position: relative;
    background-color: white;
}

#content-frame {
    width: 100%;
    height: 100%;
    border: none;
    display: block;
}
"""

public_script_js = """const form = document.getElementById('proxy-form');
const urlInput = document.getElementById('url-input');
const frame = document.getElementById('content-frame');
const copyBtn = document.getElementById('copy-url-button');
const clearBtn = document.getElementById('clear-all-button');

form.addEventListener('submit', (e) => {
    e.preventDefault();
    let url = urlInput.value.trim();

    if (!url) return;

    if (!url.startsWith('http://') && !url.startsWith('https://')) {
        url = 'https://' + url;
    }

    // Encode the target URL to handle special characters safely
    const proxyUrl = `/proxy?url=${encodeURIComponent(url)}`;
    
    // Set the iframe src to our proxy endpoint
    frame.src = proxyUrl;
});

copyBtn.addEventListener('click', () => {
    if (urlInput.value) {
        navigator.clipboard.writeText(urlInput.value)
            .then(() => {
                const originalText = copyBtn.innerText;
                copyBtn.innerText = 'Copied!';
                setTimeout(() => copyBtn.innerText = originalText, 1500);
            })
            .catch(err => console.error('Failed to copy', err));
    }
});

clearBtn.addEventListener('click', () => {
    urlInput.value = '';
    frame.src = 'about:blank';
});
"""

api_index_js = """const express = require('express');
const axios = require('axios');
const app = express();

// Vercel requires the app to be exported
module.exports = app;

app.get('/proxy', async (req, res) => {
    const targetUrl = req.query.url;

    if (!targetUrl) {
        return res.status(400).send('URL is required. Usage: /proxy?url=https://example.com');
    }

    try {
        // Parse the target URL to resolve relative paths later
        const urlObj = new URL(targetUrl);
        const baseUrl = urlObj.origin;

        const response = await axios.get(targetUrl, {
            headers: { 
                // Mimic a real browser to avoid being blocked by basic bot detection
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36' 
            },
            responseType: 'arraybuffer', // Handle binary data (images, etc.) correctly
            validateStatus: () => true // Do not throw on 404/500 from target
        });

        const contentType = response.headers['content-type'] || '';

        // --- Bypass Security Headers ---
        // Remove headers that prevent iframe embedding
        res.removeHeader('X-Frame-Options');
        res.removeHeader('Content-Security-Policy');
        res.removeHeader('X-Content-Type-Options');
        
        // Allow CORS
        res.setHeader('Access-Control-Allow-Origin', '*');
        res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
        res.setHeader('Content-Type', contentType);

        // --- Content Rewriting Logic ---
        // Only rewrite text-based content (HTML, CSS, JS, JSON)
        if (contentType.includes('text') || contentType.includes('javascript') || contentType.includes('json') || contentType.includes('xml')) {
            let content = response.data.toString('utf-8');

            // Function to rewrite URL to go through our proxy
            const rewriteUrl = (match) => {
                try {
                    // Resolve relative paths to absolute, then wrap in proxy
                    const absoluteUrl = new URL(match, targetUrl).href;
                    return `/proxy?url=${encodeURIComponent(absoluteUrl)}`;
                } catch (e) {
                    return match;
                }
            };

            // 1. Rewrite HTML attributes: href, src, action
            content = content.replace(/(?:href|src|action)=["']([^"']+)["']/g, (full, url) => {
                const parts = full.split('=');
                const attr = parts[0];
                const quote = full[parts[0].length + 1]; // " or '
                return `${attr}=${quote}${rewriteUrl(url)}${quote}`;
            });

            // 2. Rewrite CSS: url(...)
            content = content.replace(/url\(["']?([^"')]+)["']?\)/g, (full, url) => {
                return `url("${rewriteUrl(url)}")`;
            });
            
            // 3. Simple fix for srcset (images)
            content = content.replace(/srcset=["']([^"']+)["']/g, (full, srcset) => {
                 const newSrcset = srcset.split(',').map(srcDef => {
                     const [url, size] = srcDef.trim().split(' ');
                     return `${rewriteUrl(url)} ${size || ''}`;
                 }).join(', ');
                 return `srcset="${newSrcset}"`;
            });

            res.send(content);
        } else {
            // Return binary data (images, fonts, etc.) as is
            res.send(response.data);
        }

    } catch (error) {
        console.error('Proxy Error:', error.message);
        res.status(500).send(`Error loading page: ${error.message}`);
    }
});

// For local development
if (require.main === module) {
    const PORT = process.env.PORT || 3000;
    app.listen(PORT, () => {
        console.log(`Server running locally on http://localhost:${PORT}`);
    });
}
"""

# Create Zip file in memory
zip_buffer = io.BytesIO()
with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
    zip_file.writestr('package.json', package_json)
    zip_file.writestr('vercel.json', vercel_json)
    zip_file.writestr('public/index.html', public_index_html)
    zip_file.writestr('public/style.css', public_style_css)
    zip_file.writestr('public/script.js', public_script_js)
    zip_file.writestr('api/index.js', api_index_js)

# Prepare for download
zip_buffer.seek(0)