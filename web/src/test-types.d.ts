// Pulls @testing-library/jest-dom matchers into the type-check scope so
// expect(...).toBeDisabled() / toHaveClass() etc. compile. The runtime
// import lives in vitest.setup.ts; this just makes TypeScript aware.
import "@testing-library/jest-dom";
