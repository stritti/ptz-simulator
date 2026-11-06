// SPDX-FileCopyrightText: 2026 Stephan Strittmatter
// SPDX-License-Identifier: MIT

import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

const website = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const vitepress = join(website, 'node_modules', 'vitepress', 'bin', 'vitepress.js')

function buildSite(t, base) {
  const output = mkdtempSync(join(tmpdir(), 'ptzsim-site-'))
  t.after(() => rmSync(output, { recursive: true, force: true }))

  const result = spawnSync(
    process.execPath,
    [vitepress, 'build', website, '--outDir', output],
    { cwd: website, env: { ...process.env, BASE_PATH: base }, encoding: 'utf8' }
  )
  return { output, result }
}

for (const { name, input, base } of [
  { name: 'a project subpath', input: '/ptz-simulator', base: '/ptz-simulator/' },
  { name: 'a domain root', input: '', base: '/' }
]) {
  test(`builds working documentation at ${name}`, (t) => {
    const { output, result } = buildSite(t, input)
    assert.equal(result.status, 0, `VitePress build failed:\n${result.stdout}\n${result.stderr}`)

    const homePath = join(output, 'index.html')
    const guidePath = join(output, 'guide.html')
    assert.ok(existsSync(homePath), 'the homepage must be generated')
    assert.ok(existsSync(guidePath), 'the guide must be generated')

    const home = readFileSync(homePath, 'utf8')
    const guide = readFileSync(guidePath, 'utf8')
    assert.ok(home.includes(`href="${base}guide.html`), 'the guide link must use the Pages base')
    const screenshot = home.match(/<img\b[^>]*tui-dashboard\.png[^>]*>/)
    assert.ok(screenshot, 'the homepage must include the TUI screenshot')
    assert.ok(screenshot[0].includes(`src="${base}images/tui-dashboard.png"`))
    assert.match(screenshot[0], /alt="[^"]+"/)
    assert.ok(
      home.includes(`href="${base}images/tui-dashboard.png"`),
      'the screenshot must link to the full-size image'
    )
    assert.ok(existsSync(join(output, 'images', 'tui-dashboard.png')), 'the screenshot must be built')
    assert.match(guide, /id="running"/)
    assert.match(guide, /id="onvif-scope"/)
    assert.match(guide, /id="supported-visca-commands"/)
    assert.ok(
      guide.includes(`href="${base}guide.html#testing-onvif-clients"`),
      'the ONVIF integration link must point to the client guide'
    )
    assert.ok(
      guide.includes('id="testing-onvif-clients"'),
      'the ONVIF client guide target must be generated'
    )

    const scenePath = join(output, 'scene.html')
    assert.ok(existsSync(scenePath), 'the camera scene page must be generated')
    const scene = readFileSync(scenePath, 'utf8')
    for (const [page, html] of [['home', home], ['guide', guide], ['scene', scene]]) {
      assert.ok(
        html.includes(`src="${base}images/scene/panorama.svg"`),
        `the ${page} page must show the scene panorama under the Pages base`
      )
    }
    assert.match(scene, /id="ufo"/)
    assert.ok(scene.includes(`src="${base}images/scene/ufo-ndi.png"`))
    assert.ok(scene.includes(`src="${base}images/scene/ufo-tui.svg"`))
    assert.ok(existsSync(join(output, 'images', 'scene', 'ufo-tui.svg')), 'scene images must be built')

    const assets = [...home.matchAll(/(?:href|src)="([^"]*\/assets\/[^"]+)"/g)].map(
      (match) => match[1]
    )
    assert.ok(assets.length > 0, 'the homepage must reference built assets')
    for (const asset of assets) {
      assert.ok(asset.startsWith(`${base}assets/`), `${asset} must use the Pages base`)
      assert.ok(existsSync(join(output, asset.slice(base.length))), `${asset} must exist`)
    }
  })
}

test('rejects a Pages base path without a leading slash', (t) => {
  const { result } = buildSite(t, 'ptz-simulator')
  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /BASE_PATH must start with "\/"/)
})

test('rejects non-local Pages base paths', (t) => {
  for (const base of ['//example.com', '/ptz-simulator?version=1', '/ptz-simulator#guide']) {
    const { result } = buildSite(t, base)
    assert.notEqual(result.status, 0, `${base} must be rejected`)
    assert.match(result.stderr, /BASE_PATH must start with "\/" and be a local path/)
  }
})
