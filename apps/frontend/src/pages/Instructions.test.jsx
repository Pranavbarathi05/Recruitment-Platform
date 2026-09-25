import { render, screen, fireEvent, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Instructions from './Instructions';

// Mock useNavigate
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, useNavigate: () => mockNavigate };
});

const renderPage = () => render(<MemoryRouter><Instructions /></MemoryRouter>);

/**
 * Content-only tests for the candidate-facing Instructions page.
 * They assert meaningful text/content, not brittle DOM structure.
 */

// The page is one <section> per card; scoping to the card keeps multi-match
// counts meaningful. toHaveTextContent matches nested elements' text.
const cardByHeading = (name) =>
  screen.getByRole('heading', { name }).closest('section');
describe('Instructions Page', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  // ---------- Page shell ----------

  it('renders the page heading', () => {
    renderPage();
    expect(screen.getByText('Assessment Instructions')).toBeInTheDocument();
  });

  it('renders the Next button', () => {
    renderPage();
    expect(screen.getByText(/Next →/)).toBeInTheDocument();
  });

  it('navigates to /domains when Next is clicked', () => {
    renderPage();
    fireEvent.click(screen.getByText(/Next →/));
    expect(mockNavigate).toHaveBeenCalledWith('/domains');
  });

  // ---------- Section: Choosing Your Domain ----------

  it('explains the 1st-year Organizational-only rule', () => {
    renderPage();
    const card = cardByHeading(/Choosing Your Domain/i);
    expect(screen.getByText('1st Year', { exact: false })).toBeInTheDocument();
    expect(card).toHaveTextContent(/First-year candidates can apply only to the Organizational domain/i);
  });

  it('explains the 2nd/3rd-year Organizational-or-Technical options', () => {
    renderPage();
    const card = cardByHeading(/Choosing Your Domain/i);
    expect(screen.getByText('2nd and 3rd Year', { exact: false })).toBeInTheDocument();
    expect(card).toHaveTextContent(/Candidates can choose either Organizational or Technical/i);
  });

  it('explains the one-or-two technical domain choice', () => {
    renderPage();
    expect(
      screen.getByText(/one technical domain or two technical domains/i)
    ).toBeInTheDocument();
  });

  it('states the Organizational standalone rule', () => {
    renderPage();
    expect(
      screen.getByText(/Organizational is a standalone assessment and cannot be combined/i)
    ).toBeInTheDocument();
  });

  // ---------- Section: Assessment Pattern ----------

  it('presents the Organizational pattern', () => {
    renderPage();
    const patternCard = cardByHeading(/Assessment Pattern/i);
    expect(screen.getByRole('heading', { name: /Organizational Pattern/i })).toBeInTheDocument();
    // "20 MCQs" also appears in the year cards, so scope to the org block.
    const orgBlock = within(patternCard).getByRole('heading', { name: /Organizational Pattern/i }).parentElement;
    expect(within(orgBlock).getByText(/^20 MCQs$/)).toBeInTheDocument();
    expect(within(orgBlock).getByText(/^5 Descriptive questions$/)).toBeInTheDocument();
  });

  it('presents the 2nd-year technical pattern (1 domain)', () => {
    renderPage();
    const patternCard = cardByHeading(/Assessment Pattern/i);
    const yearBadges = within(patternCard).getAllByText('2nd Year');
    expect(yearBadges.length).toBeGreaterThanOrEqual(1);
    // The 2nd-year card shows the pattern for one and for two domains.
    const yearCard = yearBadges[0].closest('section');
    expect(yearCard).toHaveTextContent(/For one technical domain/i);
    expect(yearCard).toHaveTextContent(/2 DSA questions/);
    expect(yearCard).toHaveTextContent(/20 MCQs total/);
  });

  it('presents the 3rd-year technical pattern with Hands-On modules', () => {
    renderPage();
    const patternCard = cardByHeading(/Assessment Pattern/i);
    const yearBadges = within(patternCard).getAllByText('3rd Year');
    expect(yearBadges.length).toBeGreaterThanOrEqual(1);
    const yearCard = yearBadges[0].closest('section');
    expect(yearCard).toHaveTextContent(/1 Hands-On module/);
    expect(yearCard).toHaveTextContent(/2 Hands-On modules/);
  });

  it('states the 10 + 10 MCQ split for two technical domains', () => {
    renderPage();
    expect(
      screen.getAllByText(/20 MCQs total — split 10 \+ 10 between the two domains/i).length
    ).toBeGreaterThanOrEqual(1);
  });

  it('visually distinguishes the 2nd-year and 3rd-year technical patterns', () => {
    renderPage();
    // Both year cards carry tier labels so the tracks are obvious at a glance.
    expect(screen.getAllByText(/Technical track/i).length).toBeGreaterThanOrEqual(2);
  });

  // ---------- Section: Navigating the Assessment ----------

  it('explains the top navigation tabs without hardcoding real counts', () => {
    renderPage();
    expect(
      screen.getByRole('heading', { name: /Navigating the Assessment/i })
    ).toBeInTheDocument();
    expect(
      screen.getByText(/navigation tabs at the top/i)
    ).toBeInTheDocument();
    // The decorative example uses placeholder counts, never a real one.
    // "MCQ (n)" appears in prose and in the tab example.
    expect(screen.getAllByText('MCQ (n)', { exact: false }).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText('MCQ (20)')).not.toBeInTheDocument();
    expect(screen.queryByText('Coding (2)')).not.toBeInTheDocument();
  });

  it('does not claim every candidate receives every section', () => {
    renderPage();
    expect(
      screen.getAllByText(/only the sections it contains/i).length
    ).toBeGreaterThanOrEqual(1);
  });

  // ---------- Section: MCQs ----------

  it('renders the MCQs section with the core instructions', () => {
    renderPage();
    expect(screen.getByRole('heading', { name: /MCQs/i })).toBeInTheDocument();
    expect(
      screen.getByText(/Read each question carefully before selecting an answer/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Your answers are saved through the assessment flow/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Review your answers before finishing the assessment/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/submit before the allotted time expires/i)
    ).toBeInTheDocument();
    // No invented negative marking or attempt limits.
    expect(screen.queryByText(/negative marking/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/one attempt/i)).not.toBeInTheDocument();
  });

  // ---------- Section: DSA / Coding ----------

  it('explains the DSA question count and left-side navigation', () => {
    renderPage();
    expect(screen.getByRole('heading', { name: /DSA \/ Coding/i })).toBeInTheDocument();
    expect(
      screen.getByText(/There are 2 DSA questions where applicable/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/question list\/navigation on the left/i)
    ).toBeInTheDocument();
  });

  it('lists the allowed DSA programming languages', () => {
    renderPage();
    expect(
      screen.getByText(/Choose one programming language for each coding question from/i)
    ).toBeInTheDocument();
    expect(screen.getByText('Python')).toBeInTheDocument();
    expect(screen.getByText('Java')).toBeInTheDocument();
    expect(screen.getByText('C')).toBeInTheDocument();
    expect(screen.getByText('C++')).toBeInTheDocument();
  });

  it('states that coding submissions are irreversible', () => {
    renderPage();
    expect(
      screen.getAllByText(/Once a coding solution is submitted/i).length
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getAllByText(/cannot be edited or changed/i).length
    ).toBeGreaterThanOrEqual(1);
  });

  // ---------- Section: Hands-On ----------

  it('explains SQL/Pandas: multiple Runs, one submission', () => {
    renderPage();
    const card = cardByHeading(/^Hands-On$/i);
    expect(screen.getByRole('heading', { name: /SQL \/ Pandas/i })).toBeInTheDocument();
    expect(card).toHaveTextContent(/SQL and Pandas challenges can be Run multiple times/i);
    expect(card).toHaveTextContent(/run again as many times as needed/i);
    expect(card).toHaveTextContent(/submitted only once/i);
  });

  it('explains SQL Injection: run, query + flag fields, one submission', () => {
    renderPage();
    expect(screen.getByRole('heading', { name: /SQL Injection/i })).toBeInTheDocument();
    expect(
      screen.getByText(/determine the required SQL query and flag/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/The SQL query into the appropriate SQL\/query field/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/The discovered flag into the appropriate flag field/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/both fields contain the intended final values/i)
    ).toBeInTheDocument();
    expect(
      screen.getAllByText(/SQL Injection can be submitted/i).length
    ).toBeGreaterThanOrEqual(1);
  });

  it('does not conflate SQL Injection validation with SQL/Pandas WASM validation', () => {
    renderPage();
    // The SQL Injection section must never borrow the validator wording used
    // for SQL/Pandas WASM challenges.
    expect(
      screen.getAllByText(/SQL Injection/i).every(
        (el) => !/validat/i.test(el.textContent || '')
      )
    ).toBe(true);
  });

  // ---------- Section: Compliance ----------

  it('renders the compliance rules', () => {
    renderPage();
    expect(
      screen.getByRole('heading', { name: /Assessment Rules & Compliance/i })
    ).toBeInTheDocument();
    expect(screen.getByText(/Complete the assessment independently/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Follow instructions given by the invigilator and the platform/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Use only resources explicitly permitted/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Remain within the assessment environment/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Do not share questions, answers, code, flags, screenshots/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Submit work only through the provided platform/i)
    ).toBeInTheDocument();
  });

  // ---------- Section: Important (warnings) ----------

  it('renders the visually distinct warning section', () => {
    renderPage();
    const warning = screen.getByRole('note', { name: /Important/i });
    expect(warning).toBeInTheDocument();
    expect(warning).toHaveTextContent(/Check your answers before submitting/i);
    expect(warning).toHaveTextContent(/Coding submissions cannot be edited after submission/i);
    expect(warning).toHaveTextContent(/Hands-On SQL\/Pandas submissions can be submitted only once/i);
    expect(warning).toHaveTextContent(/SQL Injection submissions can be submitted only once/i);
    expect(warning).toHaveTextContent(/Keep track of the assessment timer/i);
    expect(warning).toHaveTextContent(/Leaving fullscreen or triggering other assessment-integrity controls may terminate the assessment/i);
    expect(warning).toHaveTextContent(/Do not attempt to circumvent security or assessment controls/i);
  });

  // ---------- Section: Need Help? ----------

  it('directs candidates to the nearest DSC Invigilator', () => {
    renderPage();
    expect(screen.getByRole('heading', { name: /Need Help\?/i })).toBeInTheDocument();
    expect(
      screen.getByText(/contact the/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/nearest DSC Invigilator immediately/i)).toBeInTheDocument();
    // Never advise refreshing/restarting as generic troubleshooting.
    expect(screen.queryByText(/refresh the page/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/restart the assessment/i)).not.toBeInTheDocument();
  });
});
