// Global test setup. Custom elements referenced by the cards that are
// normally supplied by the Home Assistant frontend (ha-card, ha-icon) are
// not defined in jsdom; that is fine — jsdom renders unknown elements as
// plain (inert) elements, which is all these tests need.
export {};
