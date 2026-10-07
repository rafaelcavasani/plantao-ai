import { test } from "node:test";
import assert from "node:assert/strict";
import { escapar } from "../js/escape.js";

test("escapa os cinco caracteres perigosos", () => {
  assert.equal(escapar(`<img src=x onerror="a('b')">&`), "&lt;img src=x onerror=&quot;a(&#39;b&#39;)&quot;&gt;&amp;");
});

test("nome com sinais comuns passa inteiro", () => {
  assert.equal(escapar("Clínica Sorriso & Cia"), "Clínica Sorriso &amp; Cia");
});

test("nulo e indefinido viram texto vazio", () => {
  assert.equal(escapar(null), "");
  assert.equal(escapar(undefined), "");
  assert.equal(escapar(0), "0");
});
