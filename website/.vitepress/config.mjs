// SPDX-FileCopyrightText: 2026 Stephan Strittmatter
// SPDX-License-Identifier: MIT

import { defineConfig } from 'vitepress'

const pagesBase = process.env.BASE_PATH || '/'
if (!/^\/(?!\/)[^?#]*$/.test(pagesBase)) {
  throw new Error('BASE_PATH must start with "/" and be a local path without a query or fragment')
}

// README.md (included as the guide) refers to images by their repository path so that
// they also show on GitHub; on the site they are served from the public directory.
function publicImagesFromReadme(md) {
  md.core.ruler.push('readme-public-images', (state) => {
    for (const token of state.tokens) {
      for (const child of token.children || []) {
        const src = child.type === 'image' && child.attrGet('src')
        if (src && src.startsWith('website/public/')) {
          child.attrSet('src', src.slice('website/public'.length))
        }
      }
    }
  })
}

export default defineConfig({
  base: pagesBase.endsWith('/') ? pagesBase : `${pagesBase}/`,
  lang: 'en-US',
  title: 'ptzsim',
  description: 'A PTZ camera simulator for ONVIF, VISCA and NDI.',
  markdown: { config: publicImagesFromReadme },
  themeConfig: {
    nav: [
      { text: 'Guide', link: '/guide' },
      { text: 'Camera scene', link: '/scene' },
      { text: 'Get started', link: '/guide#running' }
    ],
    sidebar: [
      {
        text: 'Get started',
        items: [
          { text: 'Overview', link: '/guide' },
          { text: 'Supported transports', link: '/guide#supported-transports' },
          { text: 'Run the simulator', link: '/guide#running' },
          { text: 'Keyboard control', link: '/guide#keyboard-control-tui' },
          { text: 'Camera scene', link: '/scene' }
        ]
      },
      {
        text: 'Protocols',
        items: [
          { text: 'ONVIF integration', link: '/guide#testing-onvif-clients' },
          { text: 'ONVIF scope', link: '/guide#onvif-scope' },
          { text: 'VISCA clients', link: '/guide#testing-visca-clients' },
          { text: 'VISCA commands', link: '/guide#supported-visca-commands' },
          { text: 'NDI', link: '/guide#ndi' }
        ]
      },
      {
        text: 'Development',
        items: [
          { text: 'Tests', link: '/guide#tests' },
          { text: 'References', link: '/guide#references' }
        ]
      }
    ],
    search: { provider: 'local' },
    socialLinks: [{ icon: 'github', link: 'https://github.com/stritti/ptz-simulator' }],
    footer: { message: 'A PTZ camera simulator for testing camera integrations.' }
  }
})
