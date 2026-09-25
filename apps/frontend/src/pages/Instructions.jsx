import { useNavigate } from 'react-router-dom';

/**
 * Instructions Page
 *
 * Candidate-facing documentation for the final assessment structure.
 * CONTENT/UI ONLY — this page describes the platform; it never changes it.
 *
 * Conventions kept from the existing page/theme:
 * - bg-theme-secondary cards on a bg-theme-primary page, text-theme-* colors
 * - one card per topic, bullet lists, "Next →" CTA to /domains
 * - responsive: single column, no horizontal overflow at any width
 *
 * Content rules (do not contradict the platform):
 * - The real workspace tabs are: MCQ (n) | Descriptive (n) | Hands-On (n) | Coding (n)
 * - Tab labels carry live counts, so we never hardcode counts into the
 *   navigation example.
 * - Every technical assessment carries exactly 2 DSA (coding) questions and a
 *   20-MCQ total (10 + 10 across two domains).
 * - Descriptive questions are organizational-only; hands-on modules are
 *   per-domain and only appear when a domain enables them — so the sections a
 *   candidate sees depend on their selection. Never claim every assessment
 *   has every section.
 */

// ---------- Small building blocks (local, theme-aware) ----------

function Bullet({ children }) {
  return (
    <li className="flex items-start gap-2">
      <span className="text-blue-400 mt-1 shrink-0" aria-hidden="true">•</span>
      <span>{children}</span>
    </li>
  );
}

function Card({ title, icon, children }) {
  return (
    <section className="bg-theme-secondary rounded-lg p-6 mb-6">
      <h2 className="text-xl font-bold text-theme-primary mb-4 flex items-center gap-2">
        <span className="text-2xl" aria-hidden="true">{icon}</span> {title}
      </h2>
      {children}
    </section>
  );
}

function WarningBullet({ children }) {
  return (
    <li className="flex items-start gap-2">
      <span className="text-red-400 mt-1 shrink-0" aria-hidden="true">•</span>
      <span>{children}</span>
    </li>
  );
}

function WarningCard({ title, icon = '⚠️', children }) {
  return (
    <section
      role="note"
      aria-label={title}
      className="bg-red-900/30 border border-red-500/60 rounded-lg p-5 mb-6"
    >
      <h2 className="text-lg font-bold text-red-300 mb-3 flex items-center gap-2">
        <span className="text-xl" aria-hidden="true">{icon}</span> {title}
      </h2>
      {children}
    </section>
  );
}

/** Miniature of the real workspace header tabs — decorative, no live counts. */
function NavTabsExample() {
  return (
    <div
      className="mt-3 flex flex-wrap items-center gap-2 rounded-lg bg-theme-primary p-2 w-fit max-w-full border border-theme-border"
      aria-hidden="true"
    >
      {['MCQ (n)', 'Descriptive (n)', 'Hands-On (n)', 'Coding (n)'].map((tab, i) => (
        <span
          key={tab}
          className={`px-4 py-1.5 rounded-md text-sm font-medium ${
            i === 0 ? 'bg-blue-600 text-white' : 'text-theme-muted'
          }`}
        >
          {tab}
        </span>
      ))}
    </div>
  );
}

/** Two-column pattern card: 2nd Year vs 3rd Year technical tracks. */
function YearCard({ yearLabel, tierLabel, badgeClass, children }) {
  return (
    <section className="flex-1 min-w-[240px] rounded-lg border border-theme-border bg-theme-primary p-5">
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <span className={`text-xs font-bold uppercase tracking-wide px-2 py-0.5 rounded ${badgeClass}`}>
          {yearLabel}
        </span>
        <span className="text-theme-muted text-sm">{tierLabel}</span>
      </div>
      {children}
    </section>
  );
}

// ---------- Page ----------

const Instructions = () => {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-theme-primary py-12 px-4 overflow-x-hidden">
      <div className="max-w-3xl mx-auto">
        <h1 className="text-3xl font-bold text-theme-primary mb-2 text-center">
          Assessment Instructions
        </h1>
        <p className="text-theme-secondary text-center mb-8 max-w-xl mx-auto">
          Read this before starting. Your sections, question counts, and timer
          depend on the domains and year you select.
        </p>

        {/* ============ 1. CHOOSING YOUR DOMAIN ============ */}
        <Card title="Choosing Your Domain" icon="🗂️">
          <div className="space-y-4 text-theme-secondary">
            <div>
              <h3 className="font-semibold text-theme-primary mb-1">1st Year</h3>
              <ul className="space-y-2">
                <Bullet>
                  First-year candidates can apply <strong>only</strong> to the{' '}
                  <strong>Organizational</strong> domain.
                </Bullet>
              </ul>
            </div>

            <div>
              <h3 className="font-semibold text-theme-primary mb-1">2nd and 3rd Year</h3>
              <ul className="space-y-2">
                <Bullet>
                  Candidates can choose either <strong>Organizational</strong> or{' '}
                  <strong>Technical</strong>.
                </Bullet>
                <Bullet>
                  Technical candidates may choose one technical domain or two
                  technical domains.
                </Bullet>
              </ul>
            </div>

            <div className="bg-amber-900/30 border border-amber-500/60 rounded-md px-4 py-3 text-theme-primary">
              <strong>Important:</strong> Organizational is a standalone
              assessment and cannot be combined with a technical domain.
            </div>
          </div>
        </Card>

        {/* ============ 2. ASSESSMENT PATTERN ============ */}
        <Card title="Assessment Pattern" icon="📐">
          <div className="space-y-5 text-theme-secondary">
            <div className="rounded-lg border border-theme-border bg-theme-primary p-5">
              <h3 className="font-semibold text-theme-primary mb-2">Organizational Pattern</h3>
              <ul className="space-y-2">
                <Bullet>20 MCQs</Bullet>
                <Bullet>5 Descriptive questions</Bullet>
              </ul>
            </div>

            {/* 2nd vs 3rd year side by side on wide screens, stacked on small */}
            <div className="flex flex-col md:flex-row gap-4 items-stretch">
              <YearCard yearLabel="2nd Year" tierLabel="Technical track" badgeClass="bg-blue-900/60 text-blue-200">
                <p className="text-sm text-theme-muted mb-2">For one technical domain:</p>
                <ul className="space-y-2 mb-3">
                  <Bullet>20 MCQs</Bullet>
                  <Bullet>2 DSA questions</Bullet>
                </ul>
                <p className="text-sm text-theme-muted mb-2">For two technical domains:</p>
                <ul className="space-y-2">
                  <Bullet>20 MCQs total — split 10 + 10 between the two domains</Bullet>
                  <Bullet>2 DSA questions</Bullet>
                </ul>
              </YearCard>

              <YearCard yearLabel="3rd Year" tierLabel="Technical track" badgeClass="bg-purple-900/60 text-purple-200">
                <p className="text-sm text-theme-muted mb-2">For one technical domain:</p>
                <ul className="space-y-2 mb-3">
                  <Bullet>20 MCQs</Bullet>
                  <Bullet>2 DSA questions</Bullet>
                  <Bullet>1 Hands-On module</Bullet>
                </ul>
                <p className="text-sm text-theme-muted mb-2">For two technical domains:</p>
                <ul className="space-y-2">
                  <Bullet>20 MCQs total — split 10 + 10 between the two domains</Bullet>
                  <Bullet>2 DSA questions</Bullet>
                  <Bullet>2 Hands-On modules</Bullet>
                </ul>
              </YearCard>
            </div>

            <p className="text-sm text-theme-muted">
              DSA questions are the coding questions in the assessment&apos;s
              Coding section. The sections your assessment shows depend on your
              year and domain selection.
            </p>
          </div>
        </Card>

        {/* ============ 3. NAVIGATING THE ASSESSMENT ============ */}
        <Card title="Navigating the Assessment" icon="🧭">
          <ul className="space-y-3 text-theme-secondary">
            <Bullet>
              Use the <strong>navigation tabs at the top</strong> of the
              assessment to move between the sections of your assessment.
            </Bullet>
            <Bullet>
              Each available section appears as a tab with its question count —
              for example <em>MCQ (n) | Descriptive (n) | Hands-On (n) | Coding (n)</em>.
              The counts come from your assessment and vary by selection.
            </Bullet>
            <Bullet>
              Your assessment shows <strong>only the sections it contains</strong>:
              not every assessment includes every section.
            </Bullet>
          </ul>
          <NavTabsExample />
        </Card>

        {/* ============ 4. MCQs ============ */}
        <Card title="MCQs" icon="📝">
          <ul className="space-y-3 text-theme-secondary">
            <Bullet>Read each question carefully before selecting an answer.</Bullet>
            <Bullet>Select the option you believe is correct.</Bullet>
            <Bullet>Your answers are saved through the assessment flow.</Bullet>
            <Bullet>Review your answers before finishing the assessment.</Bullet>
            <Bullet>
              Follow the assessment timer and submit before the allotted time
              expires.
            </Bullet>
            <Bullet>Do not attempt to bypass assessment restrictions.</Bullet>
          </ul>
        </Card>

        {/* ============ 5. DSA / CODING ============ */}
        <Card title="DSA / Coding" icon="💻">
          <ul className="space-y-3 text-theme-secondary">
            <Bullet>There are 2 DSA questions where applicable.</Bullet>
            <Bullet>
              Use the question list/navigation on the left to switch between the
              two questions.
            </Bullet>
            <li className="flex items-start gap-2">
              <span className="text-blue-400 mt-1 shrink-0" aria-hidden="true">•</span>
              <span>
                Choose one programming language for each coding question from:
                <span className="flex flex-wrap gap-2 mt-2">
                  {['Python', 'Java', 'C', 'C++'].map((lang) => (
                    <span
                      key={lang}
                      className="text-xs font-medium px-2.5 py-1 rounded bg-theme-primary border border-theme-border text-theme-primary"
                    >
                      {lang}
                    </span>
                  ))}
                </span>
              </span>
            </li>
            <Bullet>
              Write and test your solution using the available{' '}
              <strong>Run</strong> functionality.
            </Bullet>
            <Bullet>Review your solution carefully before submitting.</Bullet>
            <Bullet>
              Once a coding solution is submitted, it{' '}
              <strong>cannot be edited or changed</strong>.
            </Bullet>
            <Bullet>
              Make sure you are satisfied with your final code before pressing{' '}
              <strong>Submit</strong>.
            </Bullet>
          </ul>
        </Card>

        {/* ============ 6. HANDS-ON ============ */}
        <Card title="Hands-On" icon="🧪">
          <div className="space-y-5 text-theme-secondary">
            <div>
              <h3 className="font-semibold text-theme-primary mb-2">SQL / Pandas</h3>
              <ul className="space-y-2">
                <Bullet>
                  SQL and Pandas challenges can be <strong>Run</strong> multiple
                  times — use Run to test and debug your solution before
                  submitting.
                </Bullet>
                <Bullet>
                  You can make changes and run again as many times as needed.
                </Bullet>
                <Bullet>
                  A Hands-On SQL/Pandas challenge can be submitted{' '}
                  <strong>only once</strong>. Once submitted, the submission
                  cannot be changed.
                </Bullet>
              </ul>
            </div>

            <div>
              <h3 className="font-semibold text-theme-primary mb-2">SQL Injection</h3>
              <ul className="space-y-2">
                <Bullet>
                  You may <strong>Run</strong> the challenge as many times as
                  needed.
                </Bullet>
                <Bullet>
                  Use the provided challenge environment to determine the
                  required SQL query and flag.
                </Bullet>
                <Bullet>Before submitting, paste:</Bullet>
              </ul>
              <ol className="list-decimal list-inside ml-6 mt-1 space-y-1 text-theme-secondary">
                <li>The SQL query into the appropriate SQL/query field.</li>
                <li>The discovered flag into the appropriate flag field.</li>
              </ol>
              <ul className="space-y-2 mt-2">
                <Bullet>
                  Make sure both fields contain the intended final values before
                  submitting.
                </Bullet>
                <Bullet>
                  SQL Injection can be submitted <strong>only once</strong>. Once
                  submitted, the submission cannot be changed.
                </Bullet>
              </ul>
            </div>

            <p className="text-sm text-theme-muted">
              These Hands-On types appear only when your assessment includes
              Hands-On modules.
            </p>
          </div>
        </Card>

        {/* ============ 7. COMPLIANCE ============ */}
        <Card title="Assessment Rules & Compliance" icon="🛡️">
          <p className="text-theme-secondary mb-3">Candidates must:</p>
          <ul className="space-y-3 text-theme-secondary">
            <Bullet>Complete the assessment independently.</Bullet>
            <Bullet>
              Follow instructions given by the invigilator and the platform.
            </Bullet>
            <Bullet>
              Use only resources explicitly permitted by the assessment or
              invigilator.
            </Bullet>
            <Bullet>
              Keep the assessment environment unchanged unless instructed
              otherwise.
            </Bullet>
            <Bullet>
              Remain within the assessment environment for the duration of the
              test.
            </Bullet>
            <Bullet>
              Do not attempt to bypass platform restrictions or assessment
              controls.
            </Bullet>
            <Bullet>
              Do not share questions, answers, code, flags, screenshots, or
              assessment content with other candidates.
            </Bullet>
            <Bullet>
              Do not communicate with other candidates about assessment
              questions or answers during the assessment.
            </Bullet>
            <Bullet>Submit work only through the provided platform.</Bullet>
          </ul>
        </Card>

        {/* ============ 8. IMPORTANT (WARNINGS) ============ */}
        <WarningCard title="Important">
          <ul className="space-y-2 text-red-100">
            <WarningBullet>Check your answers before submitting.</WarningBullet>
            <WarningBullet>Coding submissions cannot be edited after submission.</WarningBullet>
            <WarningBullet>
              Hands-On SQL/Pandas submissions can be submitted only once.
            </WarningBullet>
            <WarningBullet>SQL Injection submissions can be submitted only once.</WarningBullet>
            <WarningBullet>
              Once a section is submitted/finalized, its submission may not be
              editable.
            </WarningBullet>
            <WarningBullet>Keep track of the assessment timer.</WarningBullet>
            <WarningBullet>
              Leaving fullscreen or triggering other assessment-integrity
              controls may terminate the assessment according to the assessment
              rules.
            </WarningBullet>
            <WarningBullet>
              Do not attempt to circumvent security or assessment controls.
            </WarningBullet>
          </ul>
          <p className="text-red-200/80 text-sm mt-3">
            Your assessment shows only the sections it contains — not every
            assessment includes every section listed above.
          </p>
        </WarningCard>

        {/* ============ 9. NEED HELP? ============ */}
        <section className="bg-blue-900/30 border border-blue-500/60 rounded-lg p-5 mb-8">
          <h2 className="text-lg font-bold text-theme-primary mb-2 flex items-center gap-2">
            <span className="text-xl" aria-hidden="true">🙋</span> Need Help?
          </h2>
          <p className="text-theme-secondary">
            If you encounter any technical issue, unexpected behavior, or
            problem during the assessment, contact the{' '}
            <strong className="text-theme-primary">nearest DSC Invigilator immediately</strong>.
          </p>
        </section>

        {/* Next Button */}
        <div className="flex justify-center">
          <button
            onClick={() => navigate('/domains')}
            className="px-8 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-semibold text-lg transition-colors"
          >
            Next →
          </button>
        </div>
      </div>
    </div>
  );
};

export default Instructions;
