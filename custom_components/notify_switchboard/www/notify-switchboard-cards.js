/**
 * @license
 * Copyright 2019 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const q = globalThis, ae = q.ShadowRoot && (q.ShadyCSS === void 0 || q.ShadyCSS.nativeShadow) && "adoptedStyleSheets" in Document.prototype && "replace" in CSSStyleSheet.prototype, ce = Symbol(), pe = /* @__PURE__ */ new WeakMap();
let Ce = class {
  constructor(e, t, s) {
    if (this._$cssResult$ = !0, s !== ce) throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");
    this.cssText = e, this.t = t;
  }
  get styleSheet() {
    let e = this.o;
    const t = this.t;
    if (ae && e === void 0) {
      const s = t !== void 0 && t.length === 1;
      s && (e = pe.get(t)), e === void 0 && ((this.o = e = new CSSStyleSheet()).replaceSync(this.cssText), s && pe.set(t, e));
    }
    return e;
  }
  toString() {
    return this.cssText;
  }
};
const qe = (n) => new Ce(typeof n == "string" ? n : n + "", void 0, ce), D = (n, ...e) => {
  const t = n.length === 1 ? n[0] : e.reduce((s, i, o) => s + ((r) => {
    if (r._$cssResult$ === !0) return r.cssText;
    if (typeof r == "number") return r;
    throw Error("Value passed to 'css' function must be a 'css' function result: " + r + ". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.");
  })(i) + n[o + 1], n[0]);
  return new Ce(t, n, ce);
}, Be = (n, e) => {
  if (ae) n.adoptedStyleSheets = e.map((t) => t instanceof CSSStyleSheet ? t : t.styleSheet);
  else for (const t of e) {
    const s = document.createElement("style"), i = q.litNonce;
    i !== void 0 && s.setAttribute("nonce", i), s.textContent = t.cssText, n.appendChild(s);
  }
}, fe = ae ? (n) => n : (n) => n instanceof CSSStyleSheet ? ((e) => {
  let t = "";
  for (const s of e.cssRules) t += s.cssText;
  return qe(t);
})(n) : n;
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const { is: Fe, defineProperty: We, getOwnPropertyDescriptor: Ve, getOwnPropertyNames: Ye, getOwnPropertySymbols: Ke, getPrototypeOf: Je } = Object, J = globalThis, me = J.trustedTypes, Ge = me ? me.emptyScript : "", Ze = J.reactiveElementPolyfillSupport, N = (n, e) => n, X = { toAttribute(n, e) {
  switch (e) {
    case Boolean:
      n = n ? Ge : null;
      break;
    case Object:
    case Array:
      n = n == null ? n : JSON.stringify(n);
  }
  return n;
}, fromAttribute(n, e) {
  let t = n;
  switch (e) {
    case Boolean:
      t = n !== null;
      break;
    case Number:
      t = n === null ? null : Number(n);
      break;
    case Object:
    case Array:
      try {
        t = JSON.parse(n);
      } catch {
        t = null;
      }
  }
  return t;
} }, Ne = (n, e) => !Fe(n, e), _e = { attribute: !0, type: String, converter: X, reflect: !1, useDefault: !1, hasChanged: Ne };
Symbol.metadata ??= Symbol("metadata"), J.litPropertyMetadata ??= /* @__PURE__ */ new WeakMap();
let S = class extends HTMLElement {
  static addInitializer(e) {
    this._$Ei(), (this.l ??= []).push(e);
  }
  static get observedAttributes() {
    return this.finalize(), this._$Eh && [...this._$Eh.keys()];
  }
  static createProperty(e, t = _e) {
    if (t.state && (t.attribute = !1), this._$Ei(), this.prototype.hasOwnProperty(e) && ((t = Object.create(t)).wrapped = !0), this.elementProperties.set(e, t), !t.noAccessor) {
      const s = Symbol(), i = this.getPropertyDescriptor(e, s, t);
      i !== void 0 && We(this.prototype, e, i);
    }
  }
  static getPropertyDescriptor(e, t, s) {
    const { get: i, set: o } = Ve(this.prototype, e) ?? { get() {
      return this[t];
    }, set(r) {
      this[t] = r;
    } };
    return { get: i, set(r) {
      const l = i?.call(this);
      o?.call(this, r), this.requestUpdate(e, l, s);
    }, configurable: !0, enumerable: !0 };
  }
  static getPropertyOptions(e) {
    return this.elementProperties.get(e) ?? _e;
  }
  static _$Ei() {
    if (this.hasOwnProperty(N("elementProperties"))) return;
    const e = Je(this);
    e.finalize(), e.l !== void 0 && (this.l = [...e.l]), this.elementProperties = new Map(e.elementProperties);
  }
  static finalize() {
    if (this.hasOwnProperty(N("finalized"))) return;
    if (this.finalized = !0, this._$Ei(), this.hasOwnProperty(N("properties"))) {
      const t = this.properties, s = [...Ye(t), ...Ke(t)];
      for (const i of s) this.createProperty(i, t[i]);
    }
    const e = this[Symbol.metadata];
    if (e !== null) {
      const t = litPropertyMetadata.get(e);
      if (t !== void 0) for (const [s, i] of t) this.elementProperties.set(s, i);
    }
    this._$Eh = /* @__PURE__ */ new Map();
    for (const [t, s] of this.elementProperties) {
      const i = this._$Eu(t, s);
      i !== void 0 && this._$Eh.set(i, t);
    }
    this.elementStyles = this.finalizeStyles(this.styles);
  }
  static finalizeStyles(e) {
    const t = [];
    if (Array.isArray(e)) {
      const s = new Set(e.flat(1 / 0).reverse());
      for (const i of s) t.unshift(fe(i));
    } else e !== void 0 && t.push(fe(e));
    return t;
  }
  static _$Eu(e, t) {
    const s = t.attribute;
    return s === !1 ? void 0 : typeof s == "string" ? s : typeof e == "string" ? e.toLowerCase() : void 0;
  }
  constructor() {
    super(), this._$Ep = void 0, this.isUpdatePending = !1, this.hasUpdated = !1, this._$Em = null, this._$Ev();
  }
  _$Ev() {
    this._$ES = new Promise((e) => this.enableUpdating = e), this._$AL = /* @__PURE__ */ new Map(), this._$E_(), this.requestUpdate(), this.constructor.l?.forEach((e) => e(this));
  }
  addController(e) {
    (this._$EO ??= /* @__PURE__ */ new Set()).add(e), this.renderRoot !== void 0 && this.isConnected && e.hostConnected?.();
  }
  removeController(e) {
    this._$EO?.delete(e);
  }
  _$E_() {
    const e = /* @__PURE__ */ new Map(), t = this.constructor.elementProperties;
    for (const s of t.keys()) this.hasOwnProperty(s) && (e.set(s, this[s]), delete this[s]);
    e.size > 0 && (this._$Ep = e);
  }
  createRenderRoot() {
    const e = this.shadowRoot ?? this.attachShadow(this.constructor.shadowRootOptions);
    return Be(e, this.constructor.elementStyles), e;
  }
  connectedCallback() {
    this.renderRoot ??= this.createRenderRoot(), this.enableUpdating(!0), this._$EO?.forEach((e) => e.hostConnected?.());
  }
  enableUpdating(e) {
  }
  disconnectedCallback() {
    this._$EO?.forEach((e) => e.hostDisconnected?.());
  }
  attributeChangedCallback(e, t, s) {
    this._$AK(e, s);
  }
  _$ET(e, t) {
    const s = this.constructor.elementProperties.get(e), i = this.constructor._$Eu(e, s);
    if (i !== void 0 && s.reflect === !0) {
      const o = (s.converter?.toAttribute !== void 0 ? s.converter : X).toAttribute(t, s.type);
      this._$Em = e, o == null ? this.removeAttribute(i) : this.setAttribute(i, o), this._$Em = null;
    }
  }
  _$AK(e, t) {
    const s = this.constructor, i = s._$Eh.get(e);
    if (i !== void 0 && this._$Em !== i) {
      const o = s.getPropertyOptions(i), r = typeof o.converter == "function" ? { fromAttribute: o.converter } : o.converter?.fromAttribute !== void 0 ? o.converter : X;
      this._$Em = i;
      const l = r.fromAttribute(t, o.type);
      this[i] = l ?? this._$Ej?.get(i) ?? l, this._$Em = null;
    }
  }
  requestUpdate(e, t, s, i = !1, o) {
    if (e !== void 0) {
      const r = this.constructor;
      if (i === !1 && (o = this[e]), s ??= r.getPropertyOptions(e), !((s.hasChanged ?? Ne)(o, t) || s.useDefault && s.reflect && o === this._$Ej?.get(e) && !this.hasAttribute(r._$Eu(e, s)))) return;
      this.C(e, t, s);
    }
    this.isUpdatePending === !1 && (this._$ES = this._$EP());
  }
  C(e, t, { useDefault: s, reflect: i, wrapped: o }, r) {
    s && !(this._$Ej ??= /* @__PURE__ */ new Map()).has(e) && (this._$Ej.set(e, r ?? t ?? this[e]), o !== !0 || r !== void 0) || (this._$AL.has(e) || (this.hasUpdated || s || (t = void 0), this._$AL.set(e, t)), i === !0 && this._$Em !== e && (this._$Eq ??= /* @__PURE__ */ new Set()).add(e));
  }
  async _$EP() {
    this.isUpdatePending = !0;
    try {
      await this._$ES;
    } catch (t) {
      Promise.reject(t);
    }
    const e = this.scheduleUpdate();
    return e != null && await e, !this.isUpdatePending;
  }
  scheduleUpdate() {
    return this.performUpdate();
  }
  performUpdate() {
    if (!this.isUpdatePending) return;
    if (!this.hasUpdated) {
      if (this.renderRoot ??= this.createRenderRoot(), this._$Ep) {
        for (const [i, o] of this._$Ep) this[i] = o;
        this._$Ep = void 0;
      }
      const s = this.constructor.elementProperties;
      if (s.size > 0) for (const [i, o] of s) {
        const { wrapped: r } = o, l = this[i];
        r !== !0 || this._$AL.has(i) || l === void 0 || this.C(i, void 0, o, l);
      }
    }
    let e = !1;
    const t = this._$AL;
    try {
      e = this.shouldUpdate(t), e ? (this.willUpdate(t), this._$EO?.forEach((s) => s.hostUpdate?.()), this.update(t)) : this._$EM();
    } catch (s) {
      throw e = !1, this._$EM(), s;
    }
    e && this._$AE(t);
  }
  willUpdate(e) {
  }
  _$AE(e) {
    this._$EO?.forEach((t) => t.hostUpdated?.()), this.hasUpdated || (this.hasUpdated = !0, this.firstUpdated(e)), this.updated(e);
  }
  _$EM() {
    this._$AL = /* @__PURE__ */ new Map(), this.isUpdatePending = !1;
  }
  get updateComplete() {
    return this.getUpdateComplete();
  }
  getUpdateComplete() {
    return this._$ES;
  }
  shouldUpdate(e) {
    return !0;
  }
  update(e) {
    this._$Eq &&= this._$Eq.forEach((t) => this._$ET(t, this[t])), this._$EM();
  }
  updated(e) {
  }
  firstUpdated(e) {
  }
};
S.elementStyles = [], S.shadowRootOptions = { mode: "open" }, S[N("elementProperties")] = /* @__PURE__ */ new Map(), S[N("finalized")] = /* @__PURE__ */ new Map(), Ze?.({ ReactiveElement: S }), (J.reactiveElementVersions ??= []).push("2.1.2");
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const le = globalThis, ge = (n) => n, F = le.trustedTypes, be = F ? F.createPolicy("lit-html", { createHTML: (n) => n }) : void 0, Pe = "$lit$", v = `lit$${Math.random().toFixed(9).slice(2)}$`, Te = "?" + v, Qe = `<${Te}>`, x = document, T = () => x.createComment(""), M = (n) => n === null || typeof n != "object" && typeof n != "function", de = Array.isArray, Xe = (n) => de(n) || typeof n?.[Symbol.iterator] == "function", Q = `[ 	
\f\r]`, C = /<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g, ye = /-->/g, ve = />/g, k = RegExp(`>|${Q}(?:([^\\s"'>=/]+)(${Q}*=${Q}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`, "g"), we = /'/g, $e = /"/g, Me = /^(?:script|style|textarea|title)$/i, et = (n) => (e, ...t) => ({ _$litType$: n, strings: e, values: t }), d = et(1), E = Symbol.for("lit-noChange"), u = Symbol.for("lit-nothing"), ke = /* @__PURE__ */ new WeakMap(), A = x.createTreeWalker(x, 129);
function Oe(n, e) {
  if (!de(n) || !n.hasOwnProperty("raw")) throw Error("invalid template strings array");
  return be !== void 0 ? be.createHTML(e) : e;
}
const tt = (n, e) => {
  const t = n.length - 1, s = [];
  let i, o = e === 2 ? "<svg>" : e === 3 ? "<math>" : "", r = C;
  for (let l = 0; l < t; l++) {
    const a = n[l];
    let p, f, h = -1, m = 0;
    for (; m < a.length && (r.lastIndex = m, f = r.exec(a), f !== null); ) m = r.lastIndex, r === C ? f[1] === "!--" ? r = ye : f[1] !== void 0 ? r = ve : f[2] !== void 0 ? (Me.test(f[2]) && (i = RegExp("</" + f[2], "g")), r = k) : f[3] !== void 0 && (r = k) : r === k ? f[0] === ">" ? (r = i ?? C, h = -1) : f[1] === void 0 ? h = -2 : (h = r.lastIndex - f[2].length, p = f[1], r = f[3] === void 0 ? k : f[3] === '"' ? $e : we) : r === $e || r === we ? r = k : r === ye || r === ve ? r = C : (r = k, i = void 0);
    const g = r === k && n[l + 1].startsWith("/>") ? " " : "";
    o += r === C ? a + Qe : h >= 0 ? (s.push(p), a.slice(0, h) + Pe + a.slice(h) + v + g) : a + v + (h === -2 ? l : g);
  }
  return [Oe(n, o + (n[t] || "<?>") + (e === 2 ? "</svg>" : e === 3 ? "</math>" : "")), s];
};
class O {
  constructor({ strings: e, _$litType$: t }, s) {
    let i;
    this.parts = [];
    let o = 0, r = 0;
    const l = e.length - 1, a = this.parts, [p, f] = tt(e, t);
    if (this.el = O.createElement(p, s), A.currentNode = this.el.content, t === 2 || t === 3) {
      const h = this.el.content.firstChild;
      h.replaceWith(...h.childNodes);
    }
    for (; (i = A.nextNode()) !== null && a.length < l; ) {
      if (i.nodeType === 1) {
        if (i.hasAttributes()) for (const h of i.getAttributeNames()) if (h.endsWith(Pe)) {
          const m = f[r++], g = i.getAttribute(h).split(v), $ = /([.?@])?(.*)/.exec(m);
          a.push({ type: 1, index: o, name: $[2], strings: g, ctor: $[1] === "." ? it : $[1] === "?" ? nt : $[1] === "@" ? ot : G }), i.removeAttribute(h);
        } else h.startsWith(v) && (a.push({ type: 6, index: o }), i.removeAttribute(h));
        if (Me.test(i.tagName)) {
          const h = i.textContent.split(v), m = h.length - 1;
          if (m > 0) {
            i.textContent = F ? F.emptyScript : "";
            for (let g = 0; g < m; g++) i.append(h[g], T()), A.nextNode(), a.push({ type: 2, index: ++o });
            i.append(h[m], T());
          }
        }
      } else if (i.nodeType === 8) if (i.data === Te) a.push({ type: 2, index: o });
      else {
        let h = -1;
        for (; (h = i.data.indexOf(v, h + 1)) !== -1; ) a.push({ type: 7, index: o }), h += v.length - 1;
      }
      o++;
    }
  }
  static createElement(e, t) {
    const s = x.createElement("template");
    return s.innerHTML = e, s;
  }
}
function z(n, e, t = n, s) {
  if (e === E) return e;
  let i = s !== void 0 ? t._$Co?.[s] : t._$Cl;
  const o = M(e) ? void 0 : e._$litDirective$;
  return i?.constructor !== o && (i?._$AO?.(!1), o === void 0 ? i = void 0 : (i = new o(n), i._$AT(n, t, s)), s !== void 0 ? (t._$Co ??= [])[s] = i : t._$Cl = i), i !== void 0 && (e = z(n, i._$AS(n, e.values), i, s)), e;
}
class st {
  constructor(e, t) {
    this._$AV = [], this._$AN = void 0, this._$AD = e, this._$AM = t;
  }
  get parentNode() {
    return this._$AM.parentNode;
  }
  get _$AU() {
    return this._$AM._$AU;
  }
  u(e) {
    const { el: { content: t }, parts: s } = this._$AD, i = (e?.creationScope ?? x).importNode(t, !0);
    A.currentNode = i;
    let o = A.nextNode(), r = 0, l = 0, a = s[0];
    for (; a !== void 0; ) {
      if (r === a.index) {
        let p;
        a.type === 2 ? p = new I(o, o.nextSibling, this, e) : a.type === 1 ? p = new a.ctor(o, a.name, a.strings, this, e) : a.type === 6 && (p = new rt(o, this, e)), this._$AV.push(p), a = s[++l];
      }
      r !== a?.index && (o = A.nextNode(), r++);
    }
    return A.currentNode = x, i;
  }
  p(e) {
    let t = 0;
    for (const s of this._$AV) s !== void 0 && (s.strings !== void 0 ? (s._$AI(e, s, t), t += s.strings.length - 2) : s._$AI(e[t])), t++;
  }
}
class I {
  get _$AU() {
    return this._$AM?._$AU ?? this._$Cv;
  }
  constructor(e, t, s, i) {
    this.type = 2, this._$AH = u, this._$AN = void 0, this._$AA = e, this._$AB = t, this._$AM = s, this.options = i, this._$Cv = i?.isConnected ?? !0;
  }
  get parentNode() {
    let e = this._$AA.parentNode;
    const t = this._$AM;
    return t !== void 0 && e?.nodeType === 11 && (e = t.parentNode), e;
  }
  get startNode() {
    return this._$AA;
  }
  get endNode() {
    return this._$AB;
  }
  _$AI(e, t = this) {
    e = z(this, e, t), M(e) ? e === u || e == null || e === "" ? (this._$AH !== u && this._$AR(), this._$AH = u) : e !== this._$AH && e !== E && this._(e) : e._$litType$ !== void 0 ? this.$(e) : e.nodeType !== void 0 ? this.T(e) : Xe(e) ? this.k(e) : this._(e);
  }
  O(e) {
    return this._$AA.parentNode.insertBefore(e, this._$AB);
  }
  T(e) {
    this._$AH !== e && (this._$AR(), this._$AH = this.O(e));
  }
  _(e) {
    this._$AH !== u && M(this._$AH) ? this._$AA.nextSibling.data = e : this.T(x.createTextNode(e)), this._$AH = e;
  }
  $(e) {
    const { values: t, _$litType$: s } = e, i = typeof s == "number" ? this._$AC(e) : (s.el === void 0 && (s.el = O.createElement(Oe(s.h, s.h[0]), this.options)), s);
    if (this._$AH?._$AD === i) this._$AH.p(t);
    else {
      const o = new st(i, this), r = o.u(this.options);
      o.p(t), this.T(r), this._$AH = o;
    }
  }
  _$AC(e) {
    let t = ke.get(e.strings);
    return t === void 0 && ke.set(e.strings, t = new O(e)), t;
  }
  k(e) {
    de(this._$AH) || (this._$AH = [], this._$AR());
    const t = this._$AH;
    let s, i = 0;
    for (const o of e) i === t.length ? t.push(s = new I(this.O(T()), this.O(T()), this, this.options)) : s = t[i], s._$AI(o), i++;
    i < t.length && (this._$AR(s && s._$AB.nextSibling, i), t.length = i);
  }
  _$AR(e = this._$AA.nextSibling, t) {
    for (this._$AP?.(!1, !0, t); e !== this._$AB; ) {
      const s = ge(e).nextSibling;
      ge(e).remove(), e = s;
    }
  }
  setConnected(e) {
    this._$AM === void 0 && (this._$Cv = e, this._$AP?.(e));
  }
}
class G {
  get tagName() {
    return this.element.tagName;
  }
  get _$AU() {
    return this._$AM._$AU;
  }
  constructor(e, t, s, i, o) {
    this.type = 1, this._$AH = u, this._$AN = void 0, this.element = e, this.name = t, this._$AM = i, this.options = o, s.length > 2 || s[0] !== "" || s[1] !== "" ? (this._$AH = Array(s.length - 1).fill(new String()), this.strings = s) : this._$AH = u;
  }
  _$AI(e, t = this, s, i) {
    const o = this.strings;
    let r = !1;
    if (o === void 0) e = z(this, e, t, 0), r = !M(e) || e !== this._$AH && e !== E, r && (this._$AH = e);
    else {
      const l = e;
      let a, p;
      for (e = o[0], a = 0; a < o.length - 1; a++) p = z(this, l[s + a], t, a), p === E && (p = this._$AH[a]), r ||= !M(p) || p !== this._$AH[a], p === u ? e = u : e !== u && (e += (p ?? "") + o[a + 1]), this._$AH[a] = p;
    }
    r && !i && this.j(e);
  }
  j(e) {
    e === u ? this.element.removeAttribute(this.name) : this.element.setAttribute(this.name, e ?? "");
  }
}
class it extends G {
  constructor() {
    super(...arguments), this.type = 3;
  }
  j(e) {
    this.element[this.name] = e === u ? void 0 : e;
  }
}
class nt extends G {
  constructor() {
    super(...arguments), this.type = 4;
  }
  j(e) {
    this.element.toggleAttribute(this.name, !!e && e !== u);
  }
}
class ot extends G {
  constructor(e, t, s, i, o) {
    super(e, t, s, i, o), this.type = 5;
  }
  _$AI(e, t = this) {
    if ((e = z(this, e, t, 0) ?? u) === E) return;
    const s = this._$AH, i = e === u && s !== u || e.capture !== s.capture || e.once !== s.once || e.passive !== s.passive, o = e !== u && (s === u || i);
    i && this.element.removeEventListener(this.name, this, s), o && this.element.addEventListener(this.name, this, e), this._$AH = e;
  }
  handleEvent(e) {
    typeof this._$AH == "function" ? this._$AH.call(this.options?.host ?? this.element, e) : this._$AH.handleEvent(e);
  }
}
class rt {
  constructor(e, t, s) {
    this.element = e, this.type = 6, this._$AN = void 0, this._$AM = t, this.options = s;
  }
  get _$AU() {
    return this._$AM._$AU;
  }
  _$AI(e) {
    z(this, e);
  }
}
const at = le.litHtmlPolyfillSupport;
at?.(O, I), (le.litHtmlVersions ??= []).push("3.3.3");
const ct = (n, e, t) => {
  const s = t?.renderBefore ?? e;
  let i = s._$litPart$;
  if (i === void 0) {
    const o = t?.renderBefore ?? null;
    s._$litPart$ = i = new I(e.insertBefore(T(), o), o, void 0, t ?? {});
  }
  return i._$AI(n), i;
};
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const ue = globalThis;
class w extends S {
  constructor() {
    super(...arguments), this.renderOptions = { host: this }, this._$Do = void 0;
  }
  createRenderRoot() {
    const e = super.createRenderRoot();
    return this.renderOptions.renderBefore ??= e.firstChild, e;
  }
  update(e) {
    const t = this.render();
    this.hasUpdated || (this.renderOptions.isConnected = this.isConnected), super.update(e), this._$Do = ct(t, this.renderRoot, this.renderOptions);
  }
  connectedCallback() {
    super.connectedCallback(), this._$Do?.setConnected(!0);
  }
  disconnectedCallback() {
    super.disconnectedCallback(), this._$Do?.setConnected(!1);
  }
  render() {
    return E;
  }
}
w._$litElement$ = !0, w.finalized = !0, ue.litElementHydrateSupport?.({ LitElement: w });
const lt = ue.litElementPolyfillSupport;
lt?.({ LitElement: w });
(ue.litElementVersions ??= []).push("4.2.2");
const dt = [15, 60, 480], Ae = "07:00", xe = "sensor.switchboard_dropped_today", ee = "event.switchboard_delivery", P = "sensor.switchboard_routing_table", Z = D`
  :host {
    display: block;
    color: var(--primary-text-color);
  }

  * {
    box-sizing: border-box;
  }

  button {
    font-family: inherit;
    font-size: inherit;
    color: inherit;
  }

  .touch-target {
    min-height: 48px;
    min-width: 48px;
  }

  button:focus-visible,
  [tabindex]:focus-visible,
  summary:focus-visible,
  a:focus-visible {
    outline: 2px solid var(--primary-color, #03a9f4);
    outline-offset: 2px;
  }

  .wrap-text {
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.8125rem;
    font-weight: 500;
    border: 1px solid currentColor;
  }

  .chip ha-icon {
    --mdc-icon-size: 16px;
    width: 16px;
    height: 16px;
  }

  .chip.chip-active {
    color: var(--error-color, #db4437);
  }

  .chip.chip-acknowledged {
    color: var(--success-color, var(--state-icon-active-color, #43a047));
  }

  .chip.chip-neutral {
    color: var(--secondary-text-color);
  }

  .chip.chip-unavailable {
    color: var(--warning-color, var(--secondary-text-color));
  }

  .empty-state {
    padding: 16px;
    text-align: center;
    color: var(--secondary-text-color);
  }

  .hint {
    margin: 0;
    color: var(--secondary-text-color);
    font-size: 0.8125rem;
  }

  .action-button {
    min-height: 48px;
    padding: 0 16px;
    border-radius: 8px;
    border: 1px solid var(--divider-color, rgba(127, 127, 127, 0.3));
    background: var(--secondary-background-color, transparent);
    color: var(--primary-color, inherit);
    cursor: pointer;
    white-space: normal;
    overflow-wrap: anywhere;
  }

  .action-button[aria-disabled="true"],
  .action-button:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }

  .action-button:hover:not(:disabled):not([aria-disabled="true"]) {
    background: var(--primary-color, rgba(3, 169, 244, 0.1));
    color: var(--text-primary-color, #fff);
  }

  @media (prefers-reduced-motion: reduce) {
    * {
      transition: none !important;
      animation: none !important;
    }
  }
`, te = {
  "alerts.title": "Alerts",
  "alerts.empty": "No active alerts",
  "alerts.state.active": "Active",
  "alerts.state.acknowledged": "Acknowledged",
  "alerts.acknowledged_by": "Acknowledged by {name}",
  "alerts.state.unavailable": "Unavailable",
  "alerts.action.acknowledge": "Acknowledge",
  "alerts.action.unacknowledge": "Un-acknowledge",
  "alerts.action.snooze": "Snooze",
  "alerts.action.snooze_minutes": "Snooze {minutes} min",
  "alerts.action.snooze_minutes_everyone": "Snooze for everyone · {minutes} min",
  "alerts.action.more_info": "Show details for {name}",
  "alerts.picker.prompt": "Snooze for whom?",
  "alerts.picker.prompt_for": "Snooze {name} for whom?",
  "alerts.picker.everyone": "Everyone",
  "alerts.picker.chosen": "For: {name}",
  "alerts.picker.change": "Change",
  "alerts.dialog.close": "Close",
  "alerts.badge.label": "{active} active, {acknowledged} acknowledged, {unavailable} unavailable",
  "alerts.badge.active": "{count} active",
  "alerts.badge.acknowledged": "{count} acknowledged",
  "alerts.badge.unavailable": "{count} unavailable",
  "alerts.entity_missing": "Entity {entity} not found",
  "alerts.footer.dropped": "Dropped today: {count}",
  "alerts.footer.last_delivery": "Last delivery: {value}",
  "silence.title": "Silence",
  "silence.state.silenced": "Silenced",
  "silence.state.not_silenced": "Not silenced",
  "silence.state.unknown": "Unknown",
  "silence.snoozes.count": "{count} active snoozes",
  "silence.snoozes.none": "No active snoozes",
  "silence.snoozes.unknown": "Active snoozes: —",
  "silence.last_notification.none": "No notifications yet",
  "silence.last_notification.label": "Last notification: {value}",
  "silence.action.silence_1h": "Silence 1 h",
  "silence.action.until_wake": "Until wake",
  "silence.action.clear": "Lift silence",
  "silence.action.clear_snoozes": "Clear snoozes",
  "silence.person_missing": "Person entity not found",
  "silence.not_configured": "Select a person in the card configuration",
  "silence.service_unavailable": "Requires Notify Switchboard ≥ 0.2.0",
  "editor.title": "Title",
  "editor.mode": "Mode",
  "editor.mode.compact": "Compact",
  "editor.mode.full": "Full",
  "editor.show_acknowledged": "Show acknowledged alerts",
  "editor.entities": "Alert entities (empty = all alert.* entities)",
  "editor.target_map": "Target map (alert.entity_id: slug)",
  "editor.snooze_minutes": "Snooze durations (minutes)",
  "editor.person": "Person entity",
  "editor.person_picker": "Ask who a snooze is for (kiosk)",
  "editor.wake_time": "Wake time (HH:MM)",
  "editor.derived_since_0_7_0": "Optional since Notify Switchboard 0.7.0: derived from sensor.switchboard_routing_table when left empty.",
  "editor.form_unavailable": "The Home Assistant form editor (ha-form) is not available here. Edit this card in YAML instead."
}, ut = {
  "alerts.title": "Alertes",
  "alerts.empty": "Aucune alerte active",
  "alerts.state.active": "Active",
  "alerts.state.acknowledged": "Acquittée",
  "alerts.acknowledged_by": "Acquittée par {name}",
  "alerts.state.unavailable": "Indisponible",
  "alerts.action.acknowledge": "Acquitter",
  "alerts.action.unacknowledge": "Annuler l'acquittement",
  "alerts.action.snooze": "Reporter",
  "alerts.action.snooze_minutes": "Reporter {minutes} min",
  "alerts.action.snooze_minutes_everyone": "Reporter pour tout le monde · {minutes} min",
  "alerts.action.more_info": "Afficher le détail de {name}",
  "alerts.picker.prompt": "Reporter pour qui ?",
  "alerts.picker.prompt_for": "Reporter {name} pour qui ?",
  "alerts.picker.everyone": "Tout le monde",
  "alerts.picker.chosen": "Pour : {name}",
  "alerts.picker.change": "Changer",
  "alerts.dialog.close": "Fermer",
  "alerts.badge.label": "{active} active(s), {acknowledged} acquittée(s), {unavailable} indisponible(s)",
  "alerts.badge.active": "{count} active(s)",
  "alerts.badge.acknowledged": "{count} acquittée(s)",
  "alerts.badge.unavailable": "{count} indisponible(s)",
  "alerts.entity_missing": "Entité {entity} introuvable",
  "alerts.footer.dropped": "Abandonnées aujourd'hui : {count}",
  "alerts.footer.last_delivery": "Dernier envoi : {value}",
  "silence.title": "Silence",
  "silence.state.silenced": "En silence",
  "silence.state.not_silenced": "Non silencieux",
  "silence.state.unknown": "Inconnu",
  "silence.snoozes.count": "{count} report(s) actif(s)",
  "silence.snoozes.none": "Aucun report actif",
  "silence.snoozes.unknown": "Reports actifs : —",
  "silence.last_notification.none": "Aucune notification pour l'instant",
  "silence.last_notification.label": "Dernière notification : {value}",
  "silence.action.silence_1h": "Silence 1 h",
  "silence.action.until_wake": "Jusqu'au réveil",
  "silence.action.clear": "Lever le silence",
  "silence.action.clear_snoozes": "Effacer les reports",
  "silence.person_missing": "Entité personne introuvable",
  "silence.not_configured": "Choisissez une personne dans la configuration de la carte",
  "silence.service_unavailable": "Nécessite Notify Switchboard ≥ 0.2.0",
  "editor.title": "Titre",
  "editor.mode": "Mode",
  "editor.mode.compact": "Compact",
  "editor.mode.full": "Complet",
  "editor.show_acknowledged": "Afficher les alertes acquittées",
  "editor.entities": "Entités d'alerte (vide = toutes les alert.*)",
  "editor.target_map": "Correspondance des cibles (alert.entity_id : slug)",
  "editor.snooze_minutes": "Durées de report (minutes)",
  "editor.person": "Entité personne",
  "editor.person_picker": "Demander pour qui reporter (kiosque)",
  "editor.wake_time": "Heure de réveil (HH:MM)",
  "editor.derived_since_0_7_0": "Facultatif depuis Notify Switchboard 0.7.0 : déduit de sensor.switchboard_routing_table si laissé vide.",
  "editor.form_unavailable": "L'éditeur de formulaire Home Assistant (ha-form) n'est pas disponible ici. Modifiez cette carte en YAML."
}, ht = {
  "alerts.title": "Alertas",
  "alerts.empty": "Sin alertas activas",
  "alerts.state.active": "Activa",
  "alerts.state.acknowledged": "Reconocida",
  "alerts.acknowledged_by": "Reconocida por {name}",
  "alerts.state.unavailable": "No disponible",
  "alerts.action.acknowledge": "Reconocer",
  "alerts.action.unacknowledge": "Deshacer reconocimiento",
  "alerts.action.snooze": "Posponer",
  "alerts.action.snooze_minutes": "Posponer {minutes} min",
  "alerts.action.snooze_minutes_everyone": "Posponer para todos · {minutes} min",
  "alerts.action.more_info": "Mostrar detalles de {name}",
  "alerts.picker.prompt": "¿Posponer para quién?",
  "alerts.picker.prompt_for": "¿Posponer {name} para quién?",
  "alerts.picker.everyone": "Todos",
  "alerts.picker.chosen": "Para: {name}",
  "alerts.picker.change": "Cambiar",
  "alerts.dialog.close": "Cerrar",
  "alerts.badge.label": "{active} activa(s), {acknowledged} reconocida(s), {unavailable} no disponible(s)",
  "alerts.badge.active": "{count} activa(s)",
  "alerts.badge.acknowledged": "{count} reconocida(s)",
  "alerts.badge.unavailable": "{count} no disponible(s)",
  "alerts.entity_missing": "Entidad {entity} no encontrada",
  "alerts.footer.dropped": "Descartadas hoy: {count}",
  "alerts.footer.last_delivery": "Último envío: {value}",
  "silence.title": "Silencio",
  "silence.state.silenced": "Silenciado",
  "silence.state.not_silenced": "No silenciado",
  "silence.state.unknown": "Desconocido",
  "silence.snoozes.count": "{count} aplazamiento(s) activo(s)",
  "silence.snoozes.none": "Sin aplazamientos activos",
  "silence.snoozes.unknown": "Aplazamientos activos: —",
  "silence.last_notification.none": "Todavía sin notificaciones",
  "silence.last_notification.label": "Última notificación: {value}",
  "silence.action.silence_1h": "Silenciar 1 h",
  "silence.action.until_wake": "Hasta despertar",
  "silence.action.clear": "Quitar el silencio",
  "silence.action.clear_snoozes": "Borrar aplazamientos",
  "silence.person_missing": "Entidad de persona no encontrada",
  "silence.not_configured": "Selecciona una persona en la configuración de la tarjeta",
  "silence.service_unavailable": "Requiere Notify Switchboard ≥ 0.2.0",
  "editor.title": "Título",
  "editor.mode": "Modo",
  "editor.mode.compact": "Compacto",
  "editor.mode.full": "Completo",
  "editor.show_acknowledged": "Mostrar alertas reconocidas",
  "editor.entities": "Entidades de alerta (vacío = todas las alert.*)",
  "editor.target_map": "Mapa de objetivos (alert.entity_id: slug)",
  "editor.snooze_minutes": "Duraciones de aplazamiento (minutos)",
  "editor.person": "Entidad de persona",
  "editor.person_picker": "Preguntar para quién es el aplazamiento (quiosco)",
  "editor.wake_time": "Hora de despertar (HH:MM)",
  "editor.derived_since_0_7_0": "Opcional desde Notify Switchboard 0.7.0: se deduce de sensor.switchboard_routing_table si se deja vacío.",
  "editor.form_unavailable": "El editor de formularios de Home Assistant (ha-form) no está disponible aquí. Edita esta tarjeta en YAML."
}, pt = {
  en: te,
  fr: ut,
  es: ht
};
function ft(n) {
  return (n?.locale?.language ?? n?.language ?? "en").toLowerCase().split("-")[0] ?? "en";
}
function c(n, e, t) {
  const s = ft(n);
  let o = (pt[s] ?? te)[e] ?? te[e] ?? e;
  if (t)
    for (const [r, l] of Object.entries(t))
      o = o.replaceAll(`{${r}}`, String(l));
  return o;
}
const mt = [
  ["year", 31536e3],
  ["month", 2592e3],
  ["week", 604800],
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
  ["second", 1]
], Se = /* @__PURE__ */ new Map();
function _t(n) {
  let e = Se.get(n);
  if (!e) {
    try {
      e = new Intl.RelativeTimeFormat(n, { numeric: "always", style: "long" });
    } catch {
      e = new Intl.RelativeTimeFormat("en", { numeric: "always", style: "long" });
    }
    Se.set(n, e);
  }
  return e;
}
function se(n, e, t = /* @__PURE__ */ new Date()) {
  const s = new Date(n).getTime();
  if (Number.isNaN(s))
    return "";
  const i = Math.round((t.getTime() - s) / 1e3), o = _t(e);
  for (const [r, l] of mt)
    if (Math.abs(i) >= l || r === "second") {
      const p = Math.round(i / l);
      return o.format(-p, r);
    }
  return o.format(0, "second");
}
function he(n, e, t, s = {}) {
  const i = new CustomEvent(e, {
    bubbles: s.bubbles ?? !0,
    cancelable: s.cancelable ?? !1,
    composed: s.composed ?? !0,
    detail: t
  });
  return n.dispatchEvent(i), i;
}
const gt = /^(\d{1,2}):([0-5]\d)(?::([0-5]\d))?$/;
function De(n) {
  return typeof n == "object" && n !== null && !Array.isArray(n);
}
function bt(n) {
  return Array.isArray(n) ? n.filter((e) => typeof e == "string") : [];
}
function yt(n) {
  return Array.isArray(n) ? n.filter(
    (e) => typeof e == "number" && Number.isInteger(e) && e > 0
  ) : [];
}
function vt(n) {
  if (typeof n != "string")
    return null;
  const e = gt.exec(n.trim());
  if (!e)
    return null;
  const t = Number(e[1]);
  return t > 23 ? null : `${String(t).padStart(2, "0")}:${e[2]}`;
}
function wt(n) {
  if (!(!De(n) || typeof n.slug != "string" || n.slug === ""))
    return {
      slug: n.slug,
      ...typeof n.name == "string" ? { name: n.name } : {},
      alertEntity: typeof n.alert_entity == "string" ? n.alert_entity : null,
      snoozeMinutes: yt(n.snooze_minutes),
      allowAcknowledge: typeof n.allow_acknowledge == "boolean" ? n.allow_acknowledge : void 0,
      audience: bt(n.audience)
    };
}
const $t = /^person\.[a-z0-9_]+$/;
function kt(n) {
  if (!(!De(n) || typeof n.entity_id != "string" || !$t.test(n.entity_id)))
    return {
      entityId: n.entity_id,
      wakeTime: vt(n.wake_time),
      summary: typeof n.summary == "boolean" ? n.summary : void 0
    };
}
function Ie(n) {
  const e = n?.states?.[P];
  if (!e || e.state === "unavailable" || e.state === "unknown")
    return;
  const t = e.attributes.targets, s = e.attributes.persons;
  if (!Array.isArray(t))
    return;
  const i = t.map(wt).filter((r) => r !== void 0), o = (Array.isArray(s) ? s : []).map(kt).filter((r) => r !== void 0);
  return { targets: i, persons: o };
}
function At(n, e) {
  return n?.targets.find((t) => t.alertEntity === e);
}
function xt(n, e) {
  return n?.targets.find((t) => t.slug === e);
}
function St(n, e) {
  if (e)
    return n?.persons.find((t) => t.entityId === e)?.wakeTime ?? void 0;
}
function Et(n, e, t) {
  return (t === void 0 ? n?.persons ?? [] : (n?.persons ?? []).filter((i) => t.includes(i.entityId))).map((i) => {
    const r = e?.states?.[i.entityId]?.attributes.friendly_name;
    return {
      entityId: i.entityId,
      name: typeof r == "string" && r !== "" ? r : i.entityId
    };
  });
}
const B = "notify_switchboard";
function y(n, e) {
  return !!n.services?.[B]?.[e];
}
function zt(n, e) {
  return e?.[n];
}
function Ct(n, e, t) {
  const s = zt(n, e.targetMap), i = At(t, n), o = s ?? i?.slug, r = s ? xt(t, s) ?? i : i, l = r && r.slug === o ? r : void 0, a = e.snoozeMinutes && e.snoozeMinutes.length > 0 ? e.snoozeMinutes : void 0, p = a ? (
    // Without a row for this slug — an older router, or a `target_map`
    // naming a target it does not publish — the override is the sole
    // source, exactly as in 0.1.x.
    l ? a.filter((f) => l.snoozeMinutes.includes(f)) : a
  ) : r ? r.snoozeMinutes : dt;
  return {
    slug: o,
    source: s ? "config" : i ? "routing_table" : "none",
    // The router's own condition: a row with no `alert.*` has nothing to
    // turn off, whatever `allow_acknowledge` says.
    allowAcknowledge: r ? r.allowAcknowledge !== !1 && r.alertEntity !== null : !0,
    snoozeMinutes: p,
    audience: r?.audience
  };
}
const Nt = 8;
function L(n) {
  return typeof n == "string" && n !== "" ? n : null;
}
function Pt(n) {
  const e = n?.states?.[ee];
  if (!e || e.state === "unavailable" || e.state === "unknown")
    return;
  const t = e.attributes;
  if (t.event_type !== "acknowledged")
    return;
  const s = L(t.target);
  if (s)
    return {
      at: e.state,
      target: s,
      alertEntity: L(t.alert_entity),
      person: L(t.person),
      userId: L(t.user_id)
    };
}
function Tt(n, e) {
  if (!e)
    return;
  const { person: t, userId: s } = e;
  if (t) {
    const i = n?.states?.[t]?.attributes.friendly_name;
    return typeof i == "string" && i !== "" ? i : t;
  }
  if (s)
    return s.slice(0, Nt);
}
function Mt(n, e, t) {
  const s = n?.states?.[e]?.last_changed;
  if (typeof s != "string")
    return !1;
  const i = Date.parse(s), o = Date.parse(t);
  return Number.isNaN(i) || Number.isNaN(o) ? !1 : i > o;
}
function Ot(n, e, t) {
  const s = Pt(n);
  if (!(!s || !(t ? s.target === t : s.alertEntity === e) || Mt(n, e, s.at)))
    return Tt(n, s);
}
const Re = /^[a-z][a-z0-9_]*\.[a-z0-9_]+$/, Dt = /^([01]?\d|2[0-3]):([0-5]\d)$/;
function _(n, e, t) {
  throw new Error(`${n}: "${e}" ${t}`);
}
function It(n) {
  return typeof n == "object" && n !== null && !Array.isArray(n);
}
function He(n, e, t) {
  if (t != null)
    return typeof t != "string" && _(n, e, "must be a string"), t;
}
function Ee(n, e, t) {
  if (t != null)
    return typeof t != "boolean" && _(n, e, "must be a boolean (true or false)"), t;
}
function Rt(n, e, t, s) {
  if (t != null) {
    Array.isArray(t) || _(n, e, `must be a list of ${s}.* entity ids, not a ${typeof t}`);
    for (const i of t)
      (typeof i != "string" || !Re.test(i) || !i.startsWith(`${s}.`)) && _(n, e, `must only contain ${s}.* entity ids (got ${JSON.stringify(i)})`);
    return t;
  }
}
function Ue(n, e, t, s) {
  if (!(t == null || t === ""))
    return (typeof t != "string" || !Re.test(t) || !t.startsWith(`${s}.`)) && _(n, e, `must be a ${s}.* entity id (got ${JSON.stringify(t)})`), t;
}
function Ht(n, e, t) {
  if (t != null)
    return t !== "compact" && t !== "full" && _(n, e, `must be "compact" or "full" (got ${JSON.stringify(t)})`), t;
}
function Ut(n, e, t) {
  if (t != null) {
    Array.isArray(t) || _(n, e, `must be a list of positive whole numbers, not a ${typeof t}`);
    for (const s of t)
      (typeof s != "number" || !Number.isInteger(s) || s <= 0) && _(n, e, `must only contain positive whole numbers (got ${JSON.stringify(s)})`);
    return t;
  }
}
function Lt(n, e, t) {
  if (t != null) {
    It(t) || _(n, e, `must be a mapping of entity id to slug, not a ${typeof t}`);
    for (const [s, i] of Object.entries(t))
      typeof i != "string" && _(n, e, `must map every key to a string (${s} is a ${typeof i})`);
    return t;
  }
}
function jt(n, e, t) {
  if (!(t == null || t === ""))
    return (typeof t != "string" || !Dt.test(t.trim())) && _(n, e, `must be a 24h "HH:MM" time (got ${JSON.stringify(t)})`), t.trim();
}
const qt = 3e4, b = "switchboard-alerts-card", Bt = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "summary",
  '[tabindex]:not([tabindex="-1"])'
].join(",");
function Ft(n) {
  return n ? n.state === "unavailable" || n.state === "unknown" ? "unavailable" : n.state === "on" ? "active" : "acknowledged" : "missing";
}
const W = class W extends w {
  constructor() {
    super(...arguments), this._dialogOpen = !1, this._pickedPersons = {}, this._now = Date.now(), this._openDialog = (e) => {
      this._lastFocused = e.currentTarget, this._dialogOpen = !0, this.updateComplete.then(() => {
        this.renderRoot.querySelector(".dialog-header button")?.focus();
      });
    }, this._closeDialog = () => {
      this._dialogOpen = !1;
      const e = this._lastFocused;
      this.updateComplete.then(() => {
        const t = this.renderRoot.querySelector(".badge");
        (e?.isConnected ? e : t)?.focus();
      });
    }, this._onDialogKeydown = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation(), e.preventDefault(), this._closeDialog();
        return;
      }
      if (e.key !== "Tab")
        return;
      const t = this.renderRoot.querySelector(".dialog");
      if (!t)
        return;
      const s = Array.from(t.querySelectorAll(Bt)).filter(
        (l) => l.getAttribute("aria-hidden") !== "true"
      );
      if (s.length === 0)
        return;
      const i = s[0], o = s[s.length - 1], r = this.renderRoot.activeElement;
      e.shiftKey ? (!r || r === i || !t.contains(r)) && (e.preventDefault(), o.focus()) : (!r || r === o || !t.contains(r)) && (e.preventDefault(), i.focus());
    }, this._onSnoozeKeydown = (e) => {
      if (e.key !== "Escape")
        return;
      const t = e.currentTarget;
      if (!t.open)
        return;
      e.stopPropagation(), e.preventDefault(), t.open = !1;
      const s = t.querySelector("summary");
      s?.setAttribute("aria-expanded", "false"), s?.focus();
    };
  }
  static getConfigElement() {
    return document.createElement("switchboard-alerts-card-editor");
  }
  static getStubConfig(e) {
    return {
      type: "custom:switchboard-alerts-card",
      entities: Object.keys(e?.states ?? {}).filter((s) => s.startsWith("alert.")),
      mode: "full",
      show_acknowledged: !0
    };
  }
  /**
   * Validates every option up front. Lovelace turns a throw here into a
   * `hui-error-card` showing this message next to the offending YAML,
   * which is the only place a config mistake can be reported without
   * taking the whole view down.
   */
  setConfig(e) {
    if (!e || typeof e != "object" || Array.isArray(e))
      throw new Error(`${b}: configuration must be a mapping`);
    const t = e, s = {
      ...e,
      mode: Ht(b, "mode", t.mode) ?? "full",
      show_acknowledged: Ee(b, "show_acknowledged", t.show_acknowledged) ?? !0,
      person_picker: Ee(b, "person_picker", t.person_picker) ?? !1
    }, i = Ut(
      b,
      "snooze_minutes",
      t.snooze_minutes
    );
    i === void 0 ? delete s.snooze_minutes : s.snooze_minutes = i;
    const o = Rt(b, "entities", t.entities, "alert");
    o === void 0 ? delete s.entities : s.entities = o;
    const r = Lt(b, "target_map", t.target_map);
    r === void 0 ? delete s.target_map : s.target_map = r;
    const l = Ue(b, "person", t.person, "person");
    l === void 0 ? delete s.person : s.person = l;
    const a = He(b, "title", t.title);
    a === void 0 ? delete s.title : s.title = a, this._config = s;
  }
  getCardSize() {
    return this._config?.mode === "compact" ? 1 : Math.max(1, this._rows().length + 1);
  }
  /**
   * Sizing hints for the sections layout. The compact badge needs at
   * least 3 columns' worth of width for its title (when configured) and
   * chips to sit on one line without the sections view squeezing it down
   * to a single narrow column, which is what caused the title to wrap
   * letter by letter.
   */
  getGridOptions() {
    return this._config?.mode === "compact" ? { rows: 1, columns: 4, min_rows: 1, min_columns: 3 } : { rows: "auto", columns: 12, min_rows: 2, min_columns: 6 };
  }
  connectedCallback() {
    super.connectedCallback(), this._tickHandle = setInterval(() => {
      this._hasLiveDurations() && (this._now = Date.now());
    }, qt);
  }
  disconnectedCallback() {
    super.disconnectedCallback(), this._tickHandle && (clearInterval(this._tickHandle), this._tickHandle = void 0);
  }
  /**
   * `hass` is replaced on every state change in the whole instance. Only
   * re-render when one of the entities this card actually reads changed
   * identity, or when something other than `hass` changed.
   */
  shouldUpdate(e) {
    if (e.size !== 1 || !e.has("hass"))
      return !0;
    const t = e.get("hass"), s = this.hass;
    if (!t || !s || t.services !== s.services || t.locale !== s.locale)
      return !0;
    const i = /* @__PURE__ */ new Set([
      ...this._watchedEntityIds(t),
      ...this._watchedEntityIds(s),
      xe,
      ee,
      P
    ]);
    for (const o of i)
      if (t.states[o] !== s.states[o])
        return !0;
    return !1;
  }
  _watchedEntityIds(e) {
    return this._config?.entities?.length ? this._config.entities : Object.keys(e?.states ?? {}).filter((t) => t.startsWith("alert."));
  }
  _entityIds() {
    return this._watchedEntityIds(this.hass);
  }
  _rows() {
    if (!this.hass)
      return [];
    const e = this._config?.show_acknowledged ?? !0;
    return this._entityIds().map((t) => {
      const s = this.hass?.states[t];
      return { entityId: t, stateObj: s, kind: Ft(s) };
    }).filter((t) => t.kind === "missing" ? !0 : !(t.stateObj?.state === "idle" || t.kind === "acknowledged" && !e));
  }
  _hasLiveDurations() {
    return this._rows().some((e) => e.stateObj !== void 0);
  }
  render() {
    if (!this.hass || !this._config)
      return u;
    const e = this._rows(), t = this._config.title ?? c(this.hass, "alerts.title");
    return this._config.mode === "compact" ? d`
        ${this._renderBadge(e, t)}
        ${this._dialogOpen ? this._renderDialog(e, t) : u}
      ` : d`
      <ha-card .header=${t}>
        <div class="card-content">${this._renderList(e)}</div>
        ${this._renderFooter()}
      </ha-card>
    `;
  }
  _counts(e) {
    let t = 0, s = 0, i = 0;
    for (const o of e)
      o.kind === "active" ? t += 1 : o.kind === "acknowledged" ? s += 1 : o.kind === "unavailable" && (i += 1);
    return { active: t, acknowledged: s, unavailable: i };
  }
  _renderBadge(e, t) {
    const { active: s, acknowledged: i, unavailable: o } = this._counts(e), r = c(this.hass, "alerts.badge.label", { active: s, acknowledged: i, unavailable: o }), l = !!this._config?.title;
    return d`
      <ha-card>
        <button
          class="badge touch-target"
          type="button"
          aria-haspopup="dialog"
          aria-expanded=${this._dialogOpen ? "true" : "false"}
          aria-label="${t}: ${r}"
          @click=${this._openDialog}
        >
          ${l ? d`<span class="badge-title" title=${t}>${t}</span>` : u}
          <span class="badge-chips">
            ${this._renderBadgeChip(
      s,
      s > 0 ? "chip-active" : "chip-neutral",
      "mdi:bell-ring",
      c(this.hass, "alerts.badge.active", { count: s })
    )}
            ${i > 0 ? this._renderBadgeChip(
      i,
      "chip-acknowledged",
      "mdi:check",
      c(this.hass, "alerts.badge.acknowledged", { count: i })
    ) : u}
            ${o > 0 ? this._renderBadgeChip(
      o,
      "chip-unavailable",
      "mdi:help-circle-outline",
      c(this.hass, "alerts.badge.unavailable", { count: o })
    ) : u}
          </span>
        </button>
      </ha-card>
    `;
  }
  /** Count chips always pair the number with an icon: never color alone. */
  _renderBadgeChip(e, t, s, i) {
    return d`
      <span class="badge-count chip ${t}" role="img" aria-label=${i}>
        <ha-icon icon=${s} aria-hidden="true"></ha-icon>${e}
      </span>
    `;
  }
  _renderDialog(e, t) {
    return d`
      <div
        class="dialog-backdrop"
        role="presentation"
        @click=${(s) => {
      s.target === s.currentTarget && this._closeDialog();
    }}
        @keydown=${this._onDialogKeydown}
      >
        <div class="dialog" role="dialog" aria-modal="true" aria-label="${t}">
          <div class="dialog-header">
            <span class="wrap-text">${t}</span>
            <button
              class="action-button touch-target"
              type="button"
              aria-label="${c(this.hass, "alerts.dialog.close")}"
              @click=${this._closeDialog}
            >
              ✕
            </button>
          </div>
          <div class="dialog-content">${this._renderList(e)}</div>
          ${this._renderFooter()}
        </div>
      </div>
    `;
  }
  _renderList(e) {
    return e.length === 0 ? d`<p class="empty-state">${c(this.hass, "alerts.empty")}</p>` : d`
      <ul class="alert-list">
        ${e.map((t) => this._renderRow(t))}
      </ul>
    `;
  }
  /**
   * "Dropped today / last delivery" footer (routed_today is not shown yet), read from the router's own entities
   * (`sensor.switchboard_dropped_today`, `event.switchboard_delivery`).
   * Rendered only when those entities actually exist, so the card stays
   * correct against a router that does not publish them.
   */
  _renderFooter() {
    const e = this.hass;
    if (!e)
      return u;
    const t = e.states[xe], s = e.states[ee], i = [];
    if (t && t.state !== "unavailable" && t.state !== "unknown" && i.push(
      d`<span class="wrap-text"
          >${c(e, "alerts.footer.dropped", { count: t.state })}</span
        >`
    ), s && s.state !== "unavailable" && s.state !== "unknown") {
      const o = se(
        s.state,
        e.locale?.language ?? e.language ?? "en",
        new Date(this._now)
      );
      o && i.push(
        d`<span class="wrap-text">${c(e, "alerts.footer.last_delivery", { value: o })}</span>`
      );
    }
    return i.length === 0 ? u : d`<div class="card-footer">${i}</div>`;
  }
  _renderRow(e) {
    const t = this.hass;
    if (!t)
      return d``;
    const { entityId: s, stateObj: i, kind: o } = e;
    if (!i)
      return d`
        <li class="alert-row">
          <span class="wrap-text">${c(t, "alerts.entity_missing", { entity: s })}</span>
        </li>
      `;
    const r = i.attributes.friendly_name ?? s, l = o === "active", a = o === "unavailable", p = a ? "mdi:help-circle-outline" : i.attributes.icon ?? (l ? "mdi:alert-circle" : "mdi:alert-circle-check-outline"), f = se(
      i.last_changed,
      t.locale?.language ?? t.language ?? "en",
      new Date(this._now)
    ), h = this._resolveTarget(s), m = h.slug, g = !a && !!m && h.snoozeMinutes.length > 0 && y(t, "snooze"), $ = o === "acknowledged" ? Ot(t, s, m) : void 0;
    let R, H, U;
    return a ? (R = "chip-unavailable", H = "mdi:help-circle-outline", U = c(t, "alerts.state.unavailable")) : l ? (R = "chip-active", H = "mdi:bell-ring", U = c(t, "alerts.state.active")) : (R = "chip-acknowledged", H = "mdi:check", U = c(t, "alerts.state.acknowledged")), d`
      <li class="alert-row">
        <ha-icon class="alert-icon" icon=${p}></ha-icon>
        <div class="alert-main">
          <button
            class="alert-name wrap-text"
            type="button"
            aria-label=${c(t, "alerts.action.more_info", { name: r })}
            @click=${() => this._showMoreInfo(s)}
          >
            ${r}
          </button>
          <div class="alert-meta">
            <span class="chip ${R}">
              <ha-icon icon=${H} aria-hidden="true"></ha-icon>${U}
            </span>
            <span class="alert-since wrap-text">${f}</span>
          </div>
          ${$ ? d`<span class="acknowledged-by wrap-text"
                  >${c(t, "alerts.acknowledged_by", { name: $ })}</span
                >` : u}
        </div>
        <div class="alert-actions">
          ${a ? u : l ? d`
                    <button
                      class="action-button touch-target"
                      type="button"
                      @click=${() => this._acknowledge(s, h)}
                    >
                      ${c(t, "alerts.action.acknowledge")}
                    </button>
                  ` : d`
                    <button
                      class="action-button touch-target"
                      type="button"
                      @click=${() => this._unacknowledge(s)}
                    >
                      ${c(t, "alerts.action.unacknowledge")}
                    </button>
                  `}
          ${g ? this._renderSnoozeMenu(m, h, r) : u}
        </div>
      </li>
    `;
  }
  /**
   * A `<details>` disclosure, not a fake button: `<summary>` already has
   * its own role and keyboard behaviour, so overriding it with
   * `role="button"` would strip the expanded/collapsed announcement.
   *
   * With `person_picker` on, the same disclosure holds two steps — "who?"
   * then "how long?" — rather than a second popup, which on a wall
   * tablet would mean a dialog inside a dialog.
   */
  _renderSnoozeMenu(e, t, s) {
    const i = this.hass, o = this._personChoices(t.audience), r = o.length > 0 && this._pickedPersons[e] === void 0;
    return d`
      <div class="snooze-menu" data-slug=${e}>
        <details
          @toggle=${(l) => {
      const a = l.currentTarget;
      a.querySelector("summary")?.setAttribute("aria-expanded", a.open ? "true" : "false"), a.open || this._forgetPerson(e);
    }}
          @keydown=${this._onSnoozeKeydown}
        >
          <summary class="action-button touch-target" aria-expanded="false">
            ${c(i, "alerts.action.snooze")}
          </summary>
          ${r ? this._renderPersonPicker(e, o, s) : this._renderSnoozeDurations(e, t, o.length > 0)}
        </details>
      </div>
    `;
  }
  /** Step 1 of the kiosk picker: who is this snooze for? */
  _renderPersonPicker(e, t, s) {
    const i = this.hass;
    return d`
      <div
        class="picker-step"
        role="group"
        aria-label=${c(i, "alerts.picker.prompt_for", { name: s })}
        data-slug=${e}
      >
        <span class="picker-prompt wrap-text">${c(i, "alerts.picker.prompt")}</span>
        ${t.map(
      (o) => d`
            <button
              class="action-button touch-target picker-person"
              type="button"
              @click=${() => this._pickPerson(e, o.entityId)}
            >
              ${o.name}
            </button>
          `
    )}
        <button
          class="action-button touch-target picker-everyone"
          type="button"
          @click=${() => this._pickPerson(e, "")}
        >
          ${c(i, "alerts.picker.everyone")}
        </button>
      </div>
    `;
  }
  /** Step 2 (or the only step, without the picker): how long? */
  _renderSnoozeDurations(e, t, s) {
    const i = t.snoozeMinutes, o = this.hass, l = this._effectivePerson(e, t.audience) ? "alerts.action.snooze_minutes" : "alerts.action.snooze_minutes_everyone";
    return d`
      ${s ? d`
              <div class="picker-chosen">
                <span class="wrap-text"
                  >${c(o, "alerts.picker.chosen", {
      name: this._pickedName(e, t.audience)
    })}</span
                >
                <button
                  class="action-button touch-target picker-change"
                  type="button"
                  @click=${() => this._forgetPerson(e)}
                >
                  ${c(o, "alerts.picker.change")}
                </button>
              </div>
            ` : u}
      <div class="snooze-options" role="menu" aria-label=${c(o, "alerts.action.snooze")}>
        ${i.map(
      (a) => d`
            <button
              class="action-button touch-target"
              type="button"
              role="menuitem"
              @click=${() => this._snooze(e, a, t.audience)}
            >
              ${c(o, l, { minutes: a })}
            </button>
          `
    )}
      </div>
    `;
  }
  _showMoreInfo(e) {
    he(this, "hass-more-info", { entityId: e });
  }
  /** The routing table, when the router publishes one (0.7.0 and up). */
  _routingTable() {
    return Ie(this.hass);
  }
  /**
   * The slug, snooze durations and acknowledge permission for one alert:
   * the card's own options first, then the routing table.
   */
  _resolveTarget(e) {
    const t = {};
    return this._config?.target_map && (t.targetMap = this._config.target_map), this._config?.snooze_minutes && (t.snoozeMinutes = this._config.snooze_minutes), Ct(e, t, this._routingTable());
  }
  /**
   * The persons the picker offers for one target. Empty — so the picker
   * never appears — unless the option is on *and* the routing table names
   * somebody **in that target's audience**: a chooser with nothing to
   * choose is worse than no chooser, and a name the router would refuse
   * (`person_not_in_audience`) is worse still.
   */
  _personChoices(e) {
    return this._config?.person_picker ? Et(this._routingTable(), this.hass, e) : [];
  }
  /**
   * Who a snooze on this target is for: the picker's choice when one was
   * made, the card's `person` option otherwise. An empty string is the
   * picker's explicit "everyone", and stays empty.
   *
   * The option is dropped when the routing table names an audience this
   * person is not in: `notify_switchboard.snooze` refuses that call
   * (`person_not_in_audience`) and raises a repairs issue, so the card
   * snoozes for the whole audience instead — which is something the
   * router will actually do, and which the menu's own label then
   * announces ("Snooze for everyone · 15 min"). The picker's choices are
   * already narrowed to the audience, so a name the router would refuse
   * is never sent by either path. With no row derived — `audience`
   * `undefined` — nothing is known to contradict the option and it is
   * sent as it always was.
   */
  _effectivePerson(e, t) {
    const s = this._pickedPersons[e];
    if (s !== void 0)
      return s === "" ? void 0 : s;
    const i = this._config?.person;
    if (!(i === void 0 || t !== void 0 && !t.includes(i)))
      return i;
  }
  _pickedName(e, t) {
    const s = this._pickedPersons[e];
    return s ? this._personChoices(t).find((i) => i.entityId === s)?.name ?? s : c(this.hass, "alerts.picker.everyone");
  }
  _pickPerson(e, t) {
    this._pickedPersons = { ...this._pickedPersons, [e]: t }, this._focusAfterPick(e, ".snooze-options button");
  }
  _forgetPerson(e) {
    if (this._pickedPersons[e] === void 0)
      return;
    const t = { ...this._pickedPersons };
    delete t[e], this._pickedPersons = t, this._focusAfterPick(e, ".picker-step button");
  }
  /** Moves focus to the first control of the step that just replaced another. */
  _focusAfterPick(e, t) {
    this.updateComplete.then(() => {
      this._menuFor(e)?.querySelector(t)?.focus();
    });
  }
  _menuFor(e) {
    return Array.from(this.renderRoot.querySelectorAll(".snooze-menu")).find(
      (t) => t.dataset.slug === e
    );
  }
  /**
   * Collapses one row's disclosure once its snooze is on its way. Leaving
   * it open would sit there claiming an action the user has already taken,
   * and on a wall tablet the next person would find somebody else's
   * half-used menu. The choice is dropped first — without
   * `_forgetPerson`'s focus move, which would land inside a panel that is
   * about to close — so the reopened menu starts at "who?" again, and
   * focus goes back to the summary the user actually pressed.
   */
  _closeSnoozeMenu(e) {
    if (this._pickedPersons[e] !== void 0) {
      const i = { ...this._pickedPersons };
      delete i[e], this._pickedPersons = i;
    }
    const t = this._menuFor(e)?.querySelector("details"), s = t?.querySelector("summary");
    t && (t.open = !1), s?.setAttribute("aria-expanded", "false"), this.updateComplete.then(() => {
      s?.focus();
    });
  }
  /**
   * `notify_switchboard.acknowledge` is only called when the target is
   * known *and* accepts an acknowledgement: since router 0.7.0 the routing
   * table publishes `allow_acknowledge`, and a target that says `false`
   * would have the call refused and logged. Falling back to the native
   * `alert.turn_off` — the 0.1.x path — actually clears the alert.
   */
  async _acknowledge(e, t) {
    if (this.hass) {
      if (t.slug && t.allowAcknowledge && y(this.hass, "acknowledge")) {
        await this.hass.callService("notify_switchboard", "acknowledge", { target: t.slug });
        return;
      }
      await this.hass.callService("alert", "turn_off", { entity_id: e });
    }
  }
  async _unacknowledge(e) {
    this.hass && await this.hass.callService("alert", "turn_on", { entity_id: e });
  }
  /**
   * Without `person`, `notify_switchboard.snooze` snoozes the target for
   * the whole audience — which is what the menu label says it will do.
   */
  async _snooze(e, t, s) {
    if (!this.hass) return;
    const i = this._effectivePerson(e, s), o = { target: e, minutes: t };
    i && (o.person = i);
    const r = this.hass.callService("notify_switchboard", "snooze", o);
    this._closeSnoozeMenu(e), await r;
  }
};
W.styles = [
  Z,
  D`
      .badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        width: 100%;
        min-width: 0;
        padding: 8px 16px;
        background: transparent;
        border: none;
        cursor: pointer;
        text-align: start;
      }

      /*
       * Title never wraps mid-word: a narrow sections column would
       * otherwise break it letter by letter ("Al / ert / es"). It gets a
       * fixed flex-basis of 0 so — unlike the chips — it contributes no
       * width to the shrink calculation and is the last thing to give up
       * space; ellipsis only kicks in once .badge-chips has already
       * shrunk to its own floor.
       */
      .badge-title {
        flex: 1 1 0;
        min-width: 24px;
        font-weight: 500;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      /*
       * Chips keep a real flex-basis (their natural content width), so
       * negative (shrinking) space is taken from them before it ever
       * touches the title.
       */
      .badge-chips {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        flex: 0 1 auto;
        min-width: 0;
        overflow: hidden;
      }

      .badge-count {
        justify-content: center;
        flex-shrink: 0;
      }

      .dialog-backdrop {
        position: fixed;
        inset: 0;
        background: var(--dialog-scrim-color, rgba(0, 0, 0, 0.5));
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 100;
        padding: 16px;
      }

      .dialog {
        background: var(--card-background-color, var(--ha-card-background));
        color: var(--primary-text-color);
        border-radius: 12px;
        max-width: 480px;
        width: 100%;
        max-height: 80vh;
        overflow-y: auto;
        padding: 16px;
      }

      .dialog-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        font-size: 1.1rem;
        font-weight: 500;
        margin-bottom: 8px;
      }

      .alert-list {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 8px;
      }

      .alert-row {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        padding: 8px 0;
        border-bottom: 1px solid var(--divider-color, rgba(127, 127, 127, 0.2));
      }

      .alert-row:last-child {
        border-bottom: none;
      }

      .alert-icon {
        flex-shrink: 0;
        margin-top: 4px;
      }

      .alert-main {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 4px;
      }

      .alert-name {
        font-weight: 500;
        text-align: start;
        padding: 0;
        border: none;
        background: none;
        cursor: pointer;
        color: inherit;
        text-decoration: underline;
        text-decoration-color: var(--divider-color, rgba(127, 127, 127, 0.5));
        text-underline-offset: 3px;
      }

      .alert-meta {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
      }

      .alert-since {
        color: var(--secondary-text-color);
        font-size: 0.875rem;
      }

      .alert-actions {
        display: flex;
        flex-direction: column;
        gap: 8px;
        flex-shrink: 0;
      }

      .snooze-menu summary {
        list-style: none;
        cursor: pointer;
        display: flex;
        align-items: center;
      }

      .snooze-menu summary::-webkit-details-marker {
        display: none;
      }

      .snooze-options {
        display: flex;
        flex-direction: column;
        gap: 4px;
        margin-top: 4px;
      }

      /*
       * Kiosk person picker. It lives inside the same disclosure as the
       * durations — one panel, two steps — so a wall tablet never has to
       * hit a second popup, and the whole thing stays inside the focus
       * trap the compact dialog already installs.
       */
      .picker-step {
        display: flex;
        flex-direction: column;
        gap: 4px;
        margin-top: 4px;
      }

      .picker-prompt {
        color: var(--secondary-text-color);
        font-size: 0.8125rem;
        padding: 0 4px;
      }

      .picker-chosen {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
        font-size: 0.8125rem;
        color: var(--secondary-text-color);
        padding: 0 4px;
      }

      .acknowledged-by {
        color: var(--secondary-text-color);
        font-size: 0.8125rem;
      }

      .card-footer {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        padding: 8px 16px 16px;
        color: var(--secondary-text-color);
        font-size: 0.8125rem;
      }
    `
], W.properties = {
  hass: { attribute: !1 },
  _config: { state: !0 },
  _dialogOpen: { state: !0 },
  _now: { state: !0 },
  _pickedPersons: { state: !0 }
};
let ie = W;
customElements.get("switchboard-alerts-card") || customElements.define("switchboard-alerts-card", ie);
function Le() {
  return typeof customElements < "u" && !!customElements.get("ha-form");
}
function Wt(n) {
  return n == null || n === "" ? !0 : Array.isArray(n) ? n.length === 0 : typeof n == "object" ? Object.keys(n).length === 0 : !1;
}
function je(n) {
  const e = {};
  for (const [t, s] of Object.entries(n))
    Wt(s) || (e[t] = s);
  return e;
}
const Vt = ["5", "15", "30", "60", "120", "480"], Yt = /* @__PURE__ */ new Set(["target_map", "snooze_minutes"]), V = class V extends w {
  constructor() {
    super(...arguments), this._computeLabel = (e) => c(this.hass, `editor.${e.name}`), this._computeHelper = (e) => Yt.has(e.name) ? c(this.hass, "editor.derived_since_0_7_0") : "", this._valueChanged = (e) => {
      e.stopPropagation();
      const t = { ...e.detail?.value ?? {} };
      if ("snooze_minutes" in t) {
        const i = (Array.isArray(t.snooze_minutes) ? t.snooze_minutes : []).map((o) => Number(o)).filter((o) => Number.isInteger(o) && o > 0);
        t.snooze_minutes = i;
      }
      const s = je({
        ...this._config,
        ...t,
        type: this._config?.type ?? "custom:switchboard-alerts-card"
      });
      this._config = s, he(this, "config-changed", { config: s });
    };
  }
  setConfig(e) {
    this._config = e;
  }
  _schema() {
    return [
      { name: "title", selector: { text: {} } },
      { name: "entities", selector: { entity: { domain: "alert", multiple: !0 } } },
      {
        name: "mode",
        selector: {
          select: {
            mode: "dropdown",
            options: [
              { value: "full", label: c(this.hass, "editor.mode.full") },
              { value: "compact", label: c(this.hass, "editor.mode.compact") }
            ]
          }
        }
      },
      { name: "show_acknowledged", selector: { boolean: {} } },
      { name: "person", selector: { entity: { domain: "person" } } },
      { name: "person_picker", selector: { boolean: {} } },
      {
        name: "snooze_minutes",
        selector: { select: { multiple: !0, custom_value: !0, options: Vt } }
      },
      { name: "target_map", selector: { object: {} } }
    ];
  }
  /**
   * `snooze_minutes` is numbers in YAML but strings in the select selector.
   *
   * The field is shown **empty** when the config carries no
   * `snooze_minutes`, rather than pre-filled with the built-in defaults:
   * since router 0.7.0 an empty field means "use each target's own
   * durations", and pre-filling it would turn every card the editor
   * touches into a permanent override of the routing table.
   */
  _data() {
    const e = this._config ?? {};
    return {
      ...e,
      snooze_minutes: (e.snooze_minutes ?? []).map(String)
    };
  }
  render() {
    return this._config ? Le() ? d`
      <ha-form
        .hass=${this.hass}
        .data=${this._data()}
        .schema=${this._schema()}
        .computeLabel=${this._computeLabel}
        .computeHelper=${this._computeHelper}
        @value-changed=${this._valueChanged}
      ></ha-form>
    ` : d`<p class="fallback wrap-text">${c(this.hass, "editor.form_unavailable")}</p>` : u;
  }
};
V.styles = [
  Z,
  D`
      .fallback {
        padding: 16px;
        color: var(--secondary-text-color);
      }
    `
], V.properties = {
  hass: { attribute: !1 },
  _config: { state: !0 }
};
let ne = V;
customElements.get("switchboard-alerts-card-editor") || customElements.define("switchboard-alerts-card-editor", ne);
const Kt = /^([01]?\d|2[0-3]):([0-5]\d)$/, ze = /* @__PURE__ */ new Map();
function Jt(n) {
  const e = n ?? "";
  let t = ze.get(e);
  if (!t) {
    const s = {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23"
    };
    try {
      t = new Intl.DateTimeFormat("en-US", n ? { ...s, timeZone: n } : s);
    } catch {
      t = new Intl.DateTimeFormat("en-US", s);
    }
    ze.set(e, t);
  }
  return t;
}
function Gt(n, e) {
  const t = Jt(e).formatToParts(n);
  let s = 0, i = 0, o = 0;
  for (const r of t)
    r.type === "hour" ? s = Number(r.value) % 24 : r.type === "minute" ? i = Number(r.value) : r.type === "second" && (o = Number(r.value));
  return s * 3600 + i * 60 + o;
}
function Zt(n, e = /* @__PURE__ */ new Date(), t) {
  const s = Kt.exec(n.trim());
  if (!s)
    return null;
  const i = Number(s[1]) * 3600 + Number(s[2]) * 60, o = Gt(e, t);
  let r = i - o;
  return r <= 0 && (r += 86400), Math.max(1, Math.round(r / 60));
}
const Qt = 3e4, j = "switchboard-silence-tile", Y = class Y extends w {
  constructor() {
    super(...arguments), this._now = Date.now();
  }
  static getConfigElement() {
    return document.createElement("switchboard-silence-tile-editor");
  }
  static getStubConfig(e) {
    const t = Object.keys(e?.states ?? {}).find((i) => i.startsWith("person.")), s = {
      type: "custom:switchboard-silence-tile",
      wake_time: Ae
    };
    return t && (s.person = t), s;
  }
  setConfig(e) {
    if (!e || typeof e != "object" || Array.isArray(e))
      throw new Error(`${j}: configuration must be a mapping`);
    const t = e, s = {
      ...e
    }, i = jt(j, "wake_time", t.wake_time);
    i === void 0 ? delete s.wake_time : s.wake_time = i;
    const o = Ue(j, "person", t.person, "person");
    o === void 0 ? delete s.person : s.person = o;
    const r = He(j, "title", t.title);
    r === void 0 ? delete s.title : s.title = r, this._config = s;
  }
  getCardSize() {
    return 3;
  }
  getGridOptions() {
    return { rows: "auto", columns: 6, min_rows: 2, min_columns: 3 };
  }
  connectedCallback() {
    super.connectedCallback(), this._tickHandle = setInterval(() => {
      this._hasLiveDuration() && (this._now = Date.now());
    }, Qt);
  }
  disconnectedCallback() {
    super.disconnectedCallback(), this._tickHandle && (clearInterval(this._tickHandle), this._tickHandle = void 0);
  }
  shouldUpdate(e) {
    if (e.size !== 1 || !e.has("hass"))
      return !0;
    const t = e.get("hass"), s = this.hass;
    if (!t || !s || t.services !== s.services || t.locale !== s.locale)
      return !0;
    for (const i of this._watchedEntityIds())
      if (t.states[i] !== s.states[i])
        return !0;
    return !1;
  }
  /** The person plus the three entities derived from its object id. */
  _watchedEntityIds() {
    const e = this._config?.person, t = this._objectId();
    return !e || !t ? e ? [e, P] : [P] : [
      e,
      `binary_sensor.${t}_silenced`,
      `sensor.${t}_active_snoozes`,
      `sensor.${t}_last_notification`,
      P
    ];
  }
  _objectId() {
    const e = this._config?.person;
    if (!(!e || !e.includes(".")))
      return e.split(".")[1];
  }
  _hasLiveDuration() {
    const e = this._objectId();
    if (!e)
      return !1;
    const t = this.hass?.states[`sensor.${e}_last_notification`]?.state;
    return !!t && t !== "unknown" && t !== "unavailable" && t !== "none";
  }
  render() {
    const e = this.hass, t = this._config;
    if (!e || !t)
      return u;
    const s = t.title ?? c(e, "silence.title"), i = this._objectId();
    if (!t.person || !i)
      return d`
        <ha-card .header=${s}>
          <div class="body"><p class="empty-state">${c(e, "silence.not_configured")}</p></div>
        </ha-card>
      `;
    const o = e.states[t.person], r = e.states[`binary_sensor.${i}_silenced`], l = e.states[`sensor.${i}_active_snoozes`], a = e.states[`sensor.${i}_last_notification`], p = o?.attributes.friendly_name ?? t.person, f = o?.attributes.icon ?? "mdi:account";
    return d`
      <ha-card>
        <div class="header">
          <ha-icon icon=${f}></ha-icon>
          <span class="wrap-text"
            >${s !== p ? `${s} — ${p}` : s}</span
          >
        </div>
        <div class="body">
          ${o ? u : d`<p class="empty-state">${c(e, "silence.person_missing")}</p>`}
          ${this._renderSilencedStatus(r)} ${this._renderSnoozes(l)}
          ${this._renderLastNotification(a)} ${this._renderActions()}
        </div>
      </ha-card>
    `;
  }
  _renderSilencedStatus(e) {
    const t = this.hass;
    let s, i, o;
    return !e || e.state === "unknown" || e.state === "unavailable" ? (s = c(t, "silence.state.unknown"), i = "chip-neutral", o = "mdi:help-circle-outline") : e.state === "on" ? (s = c(t, "silence.state.silenced"), i = "chip-active", o = "mdi:bell-off") : (s = c(t, "silence.state.not_silenced"), i = "chip-acknowledged", o = "mdi:bell-ring"), d`
      <div class="status-row">
        <span class="chip ${i}">
          <ha-icon icon=${o} aria-hidden="true"></ha-icon>${s}
        </span>
      </div>
    `;
  }
  /**
   * `unavailable` / `unknown` (and a missing sensor) mean "we do not know",
   * which is not the same claim as "no snoozes" — `Number("unknown")` is
   * `NaN`, and reporting that as zero would be a lie.
   */
  _renderSnoozes(e) {
    const t = this.hass, s = e?.state;
    if (s === void 0 || s === "unknown" || s === "unavailable")
      return d`<div class="detail wrap-text">${c(t, "silence.snoozes.unknown")}</div>`;
    const i = Number(s);
    if (!Number.isFinite(i))
      return d`<div class="detail wrap-text">${c(t, "silence.snoozes.unknown")}</div>`;
    const o = i > 0 ? c(t, "silence.snoozes.count", { count: i }) : c(t, "silence.snoozes.none");
    return d`<div class="detail wrap-text">${o}</div>`;
  }
  _renderLastNotification(e) {
    const t = this.hass, s = e?.state;
    if (!s || s === "unknown" || s === "unavailable" || s === "none")
      return d`<div class="detail wrap-text">${c(t, "silence.last_notification.none")}</div>`;
    const i = new Date(s), o = Number.isNaN(i.getTime()) ? s : se(
      s,
      t?.locale?.language ?? t?.language ?? "en",
      new Date(this._now)
    );
    return d`
      <div class="detail wrap-text">${c(t, "silence.last_notification.label", { value: o })}</div>
    `;
  }
  /**
   * The wake time "Until wake" silences until: the card's own option
   * first, then this person's `wake_time` from
   * `sensor.switchboard_routing_table` (router 0.7.0), then 07:00. With
   * an older router the middle step simply is not there and the
   * behaviour is the 0.1.x one.
   */
  _wakeTime() {
    const e = this._config?.wake_time;
    return e || (St(Ie(this.hass), this._config?.person) ?? Ae);
  }
  _renderActions() {
    const e = this.hass;
    if (!e) return d``;
    const t = y(e, "silence"), s = y(e, "unsnooze"), i = y(e, "unsilence"), o = this._wakeTime(), r = Zt(o, /* @__PURE__ */ new Date(), e.config?.time_zone), l = c(e, "silence.service_unavailable"), a = !t || !s || !i;
    return d`
      <div class="actions">
        ${this._renderAction(
      c(e, "silence.action.silence_1h"),
      t,
      l,
      () => this._silence(60)
    )}
        ${this._renderAction(
      c(e, "silence.action.until_wake"),
      t && r !== null,
      l,
      () => r !== null && this._silence(r)
    )}
        ${this._renderAction(
      c(e, "silence.action.clear_snoozes"),
      s,
      l,
      () => this._clearSnoozes()
    )}
        ${this._renderAction(
      c(e, "silence.action.clear"),
      i,
      l,
      () => this._unsilence()
    )}
      </div>
      ${a ? d`<p id="switchboard-service-hint" class="hint wrap-text">${l}</p>` : u}
    `;
  }
  /**
   * `aria-disabled` rather than `disabled`: the control keeps its place in
   * the tab order so a keyboard or screen-reader user can reach it and
   * hear the reason, and the click handler simply does nothing.
   */
  _renderAction(e, t, s, i) {
    return d`
      <button
        class="action-button touch-target"
        type="button"
        aria-disabled=${t ? "false" : "true"}
        aria-describedby=${t ? u : "switchboard-service-hint"}
        title=${t ? u : s}
        @click=${() => {
      t && i();
    }}
      >
        ${e}
      </button>
    `;
  }
  async _silence(e) {
    const t = this.hass, s = this._config?.person;
    !t || !s || !y(t, "silence") || await t.callService(B, "silence", { person: s, minutes: e });
  }
  async _clearSnoozes() {
    const e = this.hass, t = this._config?.person;
    !e || !t || !y(e, "unsnooze") || await e.callService(B, "unsnooze", { person: t });
  }
  /**
   * Lifting a silence is its own 0.2.0 service. It is *not* expressible as
   * `silence(minutes: 0)` — that call is not in the router's contract and
   * was previously being invented by this card.
   */
  async _unsilence() {
    const e = this.hass, t = this._config?.person;
    !e || !t || !y(e, "unsilence") || await e.callService(B, "unsilence", { person: t });
  }
};
Y.styles = [
  Z,
  D`
      .header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 16px 16px 0;
        font-weight: 500;
      }

      .body {
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }

      .status-row {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
      }

      .detail {
        color: var(--secondary-text-color);
        font-size: 0.9rem;
      }

      .actions {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
    `
], Y.properties = {
  hass: { attribute: !1 },
  _config: { state: !0 },
  _now: { state: !0 }
};
let oe = Y;
customElements.get("switchboard-silence-tile") || customElements.define("switchboard-silence-tile", oe);
const Xt = [
  { name: "person", required: !0, selector: { entity: { domain: "person" } } },
  { name: "wake_time", selector: { time: {} } },
  { name: "title", selector: { text: {} } }
];
function es(n) {
  if (typeof n != "string")
    return n;
  const e = /^(\d{1,2}):(\d{2})/.exec(n.trim());
  return e ? `${e[1]?.padStart(2, "0")}:${e[2]}` : n;
}
const K = class K extends w {
  constructor() {
    super(...arguments), this._computeLabel = (e) => c(this.hass, `editor.${e.name}`), this._computeHelper = (e) => e.name === "wake_time" ? c(this.hass, "editor.derived_since_0_7_0") : "", this._valueChanged = (e) => {
      e.stopPropagation();
      const t = { ...e.detail?.value ?? {} };
      "wake_time" in t && (t.wake_time = es(t.wake_time));
      const s = je({
        ...this._config,
        ...t,
        type: this._config?.type ?? "custom:switchboard-silence-tile"
      });
      this._config = s, he(this, "config-changed", { config: s });
    };
  }
  setConfig(e) {
    this._config = e;
  }
  render() {
    return this._config ? Le() ? d`
      <ha-form
        .hass=${this.hass}
        .data=${this._config}
        .schema=${Xt}
        .computeLabel=${this._computeLabel}
        .computeHelper=${this._computeHelper}
        @value-changed=${this._valueChanged}
      ></ha-form>
    ` : d`<p class="fallback wrap-text">${c(this.hass, "editor.form_unavailable")}</p>` : u;
  }
};
K.styles = [
  Z,
  D`
      .fallback {
        padding: 16px;
        color: var(--secondary-text-color);
      }
    `
], K.properties = {
  hass: { attribute: !1 },
  _config: { state: !0 }
};
let re = K;
customElements.get("switchboard-silence-tile-editor") || customElements.define("switchboard-silence-tile-editor", re);
const ts = "0.10.0", ss = [
  {
    type: "switchboard-alerts-card",
    name: "Notify Switchboard — Alerts",
    description: "Lists alert.* entities routed through Notify Switchboard, with acknowledge and snooze actions.",
    preview: !0,
    documentationURL: "https://github.com/amiel-35/notify-switchboard/blob/main/docs/cards.md"
  },
  {
    type: "switchboard-silence-tile",
    name: "Notify Switchboard — Silence tile",
    description: "Shows and controls one person's Notify Switchboard silence and snooze state.",
    preview: !0,
    documentationURL: "https://github.com/amiel-35/notify-switchboard/blob/main/docs/cards.md"
  }
];
window.customCards = window.customCards || [];
for (const n of ss)
  window.customCards.some((e) => e.type === n.type) || window.customCards.push(n);
console.info(
  `%c NOTIFY-SWITCHBOARD-CARDS %c ${ts} `,
  "color: white; background: #03a9f4; font-weight: 700;",
  "color: #03a9f4; background: white; font-weight: 700;"
);
export {
  ie as SwitchboardAlertsCard,
  ne as SwitchboardAlertsCardEditor,
  oe as SwitchboardSilenceTile,
  re as SwitchboardSilenceTileEditor
};
//# sourceMappingURL=notify-switchboard-cards.js.map
