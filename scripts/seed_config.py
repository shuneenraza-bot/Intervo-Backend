"""Loads Intervo's real configuration: 4 domains, 15 job roles, their skills and weights,
responsibilities, CV aliases, related skills, coaching tips and interview question templates.

Run from the project root, after `alembic upgrade head`:

    python -m scripts.seed_config

Everything is upserted by name, so it is safe to run again. It never deletes users, jobs,
applications or interview sessions. Old configuration is cleaned up like this:
  - a skill that is not in this file is kept while a job, a role or an interview answer uses it,
    and deleted otherwise;
  - a role that is not in this file is marked inactive (hidden from candidates and new jobs),
    never deleted;
  - the old demo question templates (q1 ... q18) are removed unless an admin edited them.
Questions are conceptual: none asks the candidate to write or run code.
"""

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Domain, Job, JobRole, JobSkill, QuestionTemplate, RoleSkill, SessionAnswer, Skill


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


DOMAINS = [("tech", "Technology"), ("business", "Business"), ("marketing", "Marketing"), ("hrfin", "HR & Finance")]

# (id, title, domain, core (3), important (2), nice (1), responsibilities)
# Ids of the six roles that already existed are kept so jobs and sessions keep pointing at them.
_ROLE_TABLE = [
    ("frontend", "Frontend Developer", "tech", ["React", "JavaScript"], ["HTML", "CSS", "Git"], ["Testing", "TypeScript"],
     ["Build responsive UI", "Connect REST APIs", "Fix UI bugs", "Work with designers"]),
    ("backend", "Backend Developer", "tech", ["Python", "SQL", "REST APIs"], ["Git", "Problem solving"], ["Testing", "Docker"],
     ["Build APIs", "Design database tables", "Write tests", "Debug issues"]),
    ("qa", "Software QA Engineer", "tech", ["Manual testing", "Test case design"], ["Bug reporting", "SQL"],
     ["Test automation (Selenium)", "Communication"],
     ["Test features", "Write test cases", "Report and track bugs", "Regression testing"]),
    ("uiux", "UI/UX Designer", "tech", ["Figma", "User research"], ["Wireframing & prototyping", "Visual design"],
     ["HTML/CSS", "Communication"],
     ["Run user research", "Design flows and screens", "Build prototypes", "Hand off to developers"]),
    ("data-analyst", "Data Analyst", "tech", ["SQL", "Excel", "Data analysis"], ["Data visualization (Power BI/Tableau)", "Python"],
     ["Statistics", "Communication"],
     ["Clean data", "Build reports and dashboards", "Find trends", "Explain findings"]),
    ("analyst", "Business Analyst", "business", ["Requirements gathering", "Data analysis"],
     ["Documentation", "Excel", "Communication"], ["SQL", "Stakeholder management"],
     ["Gather requirements", "Write user stories", "Analyse processes", "Support decisions"]),
    ("project-coordinator", "Project Coordinator", "business", ["Project planning", "Communication"],
     ["Time management", "Teamwork"], ["Jira/Trello", "Risk management"],
     ["Track tasks and deadlines", "Run meetings", "Update stakeholders", "Manage risks"]),
    ("sales-cs", "Sales / Customer Success Executive", "business", ["Communication", "Negotiation"],
     ["Customer service", "CRM"], ["Excel", "Problem solving"],
     ["Handle leads", "Close deals", "Support clients", "Keep CRM updated"]),
    ("digital-marketing", "Digital Marketing Executive", "marketing", ["Social media marketing", "Paid ads (Meta/Google)"],
     ["Marketing analytics", "Content planning"], ["SEO", "Canva"],
     ["Run campaigns", "Manage ad budgets", "Track results", "Plan content calendars"]),
    ("content-seo", "Content Writer / SEO", "marketing", ["Content writing", "SEO"], ["Keyword research", "Editing"],
     ["WordPress", "Marketing analytics"],
     ["Write blogs and web copy", "Optimise for search", "Edit content", "Track rankings"]),
    ("marketing", "Marketing Associate", "marketing", ["Market research", "Campaign planning"],
     ["Communication", "Data analysis"], ["Excel", "Teamwork"],
     ["Research competitors and customers", "Support campaigns", "Prepare reports"]),
    ("hr", "HR Associate", "hrfin", ["Recruitment", "Communication"],
     ["Onboarding", "HR policies & labour law basics", "Excel"], ["HRMS tools", "Conflict resolution"],
     ["Screen CVs", "Schedule interviews", "Onboard staff", "Maintain employee records"]),
    ("accounts", "Junior Accountant", "hrfin", ["Accounting", "Excel"],
     ["Bookkeeping & reconciliation", "Taxation basics (FBR)"], ["QuickBooks/Tally", "Attention to detail"],
     ["Record transactions", "Reconcile accounts", "Prepare invoices", "Support tax filing"]),
    ("financial-analyst", "Financial Analyst", "hrfin", ["Financial analysis", "Excel"],
     ["Financial modelling", "Financial reporting"], ["Power BI", "Communication"],
     ["Analyse statements", "Build forecasts", "Prepare reports", "Support budgeting"]),
    ("payroll-admin", "Payroll / Admin Officer", "hrfin", ["Payroll processing", "Excel"],
     ["Attendance & leave management", "Taxation basics (FBR)"], ["HRMS tools", "Attention to detail"],
     ["Process salaries", "Manage attendance", "Handle deductions", "Keep records"]),
]

# (id, title, domain_id, [(skill, weight)], [responsibility lines])
ROLES = [
    (id_, title, domain, [*((s, 3) for s in core), *((s, 2) for s in important), *((s, 1) for s in nice)], duties)
    for id_, title, domain, core, important, nice, duties in _ROLE_TABLE
]

# name -> (aliases, related skills, coaching tip, technical question, keywords, follow-up)
# Aliases are matched as whole words in lower-cased CV text, so each one is a spelling or tool name
# that really points at the skill. Related skills give half credit in the CV match.
_S: dict[str, tuple] = {}


def _skill(name, aliases, related, tip, question, keywords, follow_up):
    _S[name] = (aliases, related, tip, question, keywords, follow_up)


# ---- Technology ----
_skill("React", ["react", "reactjs", "react.js", "react hooks", "redux", "next.js", "nextjs"], ["JavaScript", "TypeScript"],
       "Practise explaining state, props and re-renders with one small app you built.",
       "How do you decide what belongs in a component's state and what is passed down as props?",
       ["state", "props", "parent", "child", "re-render", "lift"],
       "What happens when two sibling components need the same piece of state?")
_skill("JavaScript", ["javascript", "js", "es6", "ecmascript", "vanilla js", "dom manipulation"], ["TypeScript", "React"],
       "Explain scope, async behaviour and the DOM in plain words, each in two sentences.",
       "Why do web pages use asynchronous operations, and how do you keep a page responsive while data loads?",
       ["asynchronous", "promise", "callback", "loading", "blocking", "response", "user"],
       "How would you show the user that something is still loading?")
_skill("HTML", ["html", "html5", "semantic html", "semantic markup"], ["CSS", "HTML/CSS"],
       "Mention semantic tags and accessibility when you describe a page's structure.",
       "Why does semantic HTML matter, and which elements do you use most when structuring a page?",
       ["semantic", "accessibility", "header", "nav", "main", "screen reader"],
       "How does semantic HTML help a screen-reader user?")
_skill("CSS", ["css", "css3", "tailwind", "tailwind css", "bootstrap", "sass", "scss", "flexbox", "css grid", "responsive design"],
       ["HTML", "HTML/CSS"],
       "Explain responsive layouts step by step: flexible units, flexbox or grid, then breakpoints.",
       "How would you make a page layout work well on both a phone and a desktop screen?",
       ["flexbox", "grid", "media query", "responsive", "breakpoint", "mobile first"],
       "Which breakpoints would you choose, and why?")
_skill("Git", ["git", "github", "gitlab", "bitbucket", "version control", "pull request", "pull requests"], ["Docker"],
       "Describe your branch, commit, pull request and review flow in that order.",
       "Describe your Git workflow when several people work on the same project.",
       ["branch", "commit", "pull request", "review", "merge", "conflict"],
       "How do you resolve a merge conflict?")
_skill("Testing", ["testing", "unit test", "unit tests", "unit testing", "jest", "pytest", "integration testing", "tdd"], ["Manual testing"],
       "Give one example: what you tested, the input, and the result you expected.",
       "How do you decide what to test when you finish a new feature?",
       ["unit", "edge case", "input", "expected", "integration", "bug"],
       "Give an example of an edge case you would test.")
_skill("TypeScript", ["typescript", "ts", "tsx"], ["JavaScript", "React"],
       "Be ready to explain why types catch mistakes earlier, with one real example.",
       "What problems do static types help prevent in a large web project?",
       ["type", "error", "compile", "refactor", "autocomplete", "interface"],
       "What is the cost of adding types to a small project?")
_skill("Python", ["python", "python3", "django", "flask", "fastapi", "pandas", "numpy"], ["SQL", "REST APIs"],
       "Say what you built with Python and what problem it solved, before naming libraries.",
       "Where have you used Python, and why was it a good fit for that task?",
       ["library", "script", "automation", "data", "web", "readable"],
       "What would you use instead if the task needed to run much faster?")
_skill("SQL", ["sql", "postgresql", "postgres", "mysql", "sql server", "sqlite", "t-sql", "joins", "database queries"], ["Data analysis", "Python"],
       "Explain a query in words: which tables, how they join, what you group by and why.",
       "What is the difference between an inner join and a left join, and when would you use each?",
       ["inner", "left", "match", "null", "rows", "table", "key"],
       "How would you find customers who have never placed an order?")
_skill("REST APIs", ["rest api", "rest apis", "restful", "restful api", "api integration", "http methods", "web api", "api development", "postman"],
       ["Python", "JavaScript"],
       "Use one concrete endpoint example and mention methods, status codes and validation.",
       "What makes a REST API well designed? Describe an endpoint you would create and what it returns.",
       ["resource", "get", "post", "status code", "json", "validation", "authentication"],
       "Which status codes would that endpoint return on success and on errors?")
_skill("Problem solving", ["problem solving", "problem-solving", "analytical thinking", "analytical skills", "troubleshooting", "root cause analysis", "debugging"], ["Testing"],
       "Show your steps: understand the problem, break it down, try a fix, verify the result.",
       "Walk me through how you would approach a problem you have never seen before.",
       ["understand", "break down", "options", "test", "verify", "ask"],
       "How do you know when to ask for help?")
_skill("Docker", ["docker", "containers", "containerization", "docker compose", "dockerfile"], ["Git"],
       "Explain what a container solves in one sentence: the app runs the same everywhere.",
       "What problem do containers solve for a development team?",
       ["environment", "consistent", "image", "isolation", "deploy", "dependencies"],
       "How is a container different from a virtual machine?")
_skill("Manual testing", ["manual testing", "functional testing", "regression testing", "exploratory testing", "smoke testing", "uat", "user acceptance testing"],
       ["Test case design", "Testing"],
       "Describe how you explore a feature: happy path first, then odd inputs and different devices.",
       "How would you test a login page by hand? What would you check besides a correct login?",
       ["valid", "invalid", "empty", "password", "error message", "lockout", "browser"],
       "Which of those checks would you do first if you had only ten minutes?")
_skill("Test case design", ["test case", "test cases", "test case design", "test scenarios", "test plan", "boundary value", "equivalence partitioning", "test coverage"],
       ["Manual testing", "Bug reporting"],
       "Show that a test case has an id, steps, test data and one clear expected result.",
       "What does a good test case contain, and how do you choose which cases to write for a new feature?",
       ["steps", "expected result", "test data", "boundary", "negative", "priority", "coverage"],
       "How do boundary values help when testing an age field that accepts 18 to 60?")
_skill("Bug reporting", ["bug report", "bug reports", "bug reporting", "defect tracking", "defect report", "jira bugs", "bugzilla", "issue tracking"],
       ["Manual testing", "Communication"],
       "Practise a bug report: title, steps to reproduce, expected and actual result, evidence.",
       "What information makes a bug report easy for a developer to act on?",
       ["steps to reproduce", "expected", "actual", "screenshot", "severity", "environment"],
       "How do you decide between severity and priority?")
_skill("Test automation (Selenium)", ["selenium", "test automation", "automation testing", "automated testing", "cypress", "playwright", "webdriver", "testng"],
       ["Testing", "Manual testing"],
       "Explain which tests you would automate first, and why not everything should be automated.",
       "How do you decide which tests are worth automating and which should stay manual?",
       ["repeat", "regression", "stable", "time", "maintenance", "manual", "return"],
       "What makes an automated test flaky, and how do you reduce that?")
_skill("Figma", ["figma", "figjam", "auto layout", "figma components", "design tokens", "sketch", "adobe xd"], ["Visual design", "Wireframing & prototyping"],
       "Describe one Figma file you built: pages, components, and how you organised them.",
       "How do you organise a Figma file so that a team can reuse and update it easily?",
       ["components", "styles", "auto layout", "naming", "library", "variants"],
       "How do you keep designs consistent when several designers work in the same file?")
_skill("User research", ["user research", "ux research", "user interviews", "usability testing", "usability test", "surveys", "personas", "user personas", "empathy map", "user journey"],
       ["Wireframing & prototyping", "Communication"],
       "Tell the story: question, method, what you learned, what you changed in the design.",
       "How would you find out why users abandon a sign-up form?",
       ["interview", "observe", "analytics", "usability test", "hypothesis", "survey", "findings"],
       "How many users would you test with, and how do you handle conflicting feedback?")
_skill("Wireframing & prototyping", ["wireframe", "wireframes", "wireframing", "prototype", "prototypes", "prototyping", "low-fidelity", "high-fidelity", "user flow", "user flows", "information architecture"],
       ["Figma", "Visual design"],
       "Explain why you start low-fidelity: cheap to change, focuses feedback on the flow.",
       "What is the difference between a wireframe and a prototype, and when do you use each?",
       ["layout", "low fidelity", "interactive", "flow", "feedback", "testing"],
       "How do you decide when a design is ready to hand to developers?")
_skill("Visual design", ["visual design", "graphic design", "ui design", "typography", "colour theory", "color theory", "layout design", "design system", "branding", "photoshop", "illustrator"],
       ["Figma", "Canva"],
       "Explain a design choice with a reason: contrast for readability, spacing for grouping.",
       "How do you use colour, typography and spacing to guide a user's attention on a screen?",
       ["hierarchy", "contrast", "spacing", "typography", "consistency", "accessibility"],
       "How do you check that your colours are readable for people with low vision?")
_skill("HTML/CSS", ["html/css", "html & css", "html and css", "html5/css3", "html css", "front-end basics"], ["HTML", "CSS"],
       "Say how you hand designs over: you can read the HTML and CSS a developer builds from them.",
       "Why is it useful for a designer to understand basic HTML and CSS?",
       ["handoff", "feasible", "responsive", "developer", "constraints", "box model"],
       "Give an example of a design idea that is hard to build in CSS.")
_skill("Excel", ["excel", "ms excel", "microsoft excel", "spreadsheets", "spreadsheet", "vlookup", "xlookup", "pivot table", "pivot tables", "google sheets", "sumifs"],
       ["Data analysis", "Data visualization (Power BI/Tableau)"],
       "Prepare a pivot-table or lookup example from a real report you made.",
       "How would you summarise a large sales sheet by region and month in Excel?",
       ["pivot", "sumifs", "filter", "region", "month", "chart"],
       "How would you keep that summary up to date when new rows are added?")
_skill("Data analysis", ["data analysis", "data analytics", "data cleaning", "exploratory analysis", "insights", "kpi", "kpis", "trend analysis"],
       ["Excel", "SQL"],
       "Structure answers as question, data, finding, recommendation.",
       "Walk me through how you would find out why sales dropped last month.",
       ["data", "compare", "segment", "trend", "cause", "recommend"],
       "Which chart would you show a manager to explain your finding?")
_skill("Data visualization (Power BI/Tableau)", ["power bi", "powerbi", "tableau", "data visualization", "data visualisation", "dashboard", "dashboards", "looker studio", "google data studio"],
       ["Data analysis", "Power BI", "Excel"],
       "Explain one dashboard: who used it, which question it answered, which chart you chose and why.",
       "How do you choose the right chart for a number you want a manager to understand quickly?",
       ["audience", "comparison", "trend", "bar", "line", "clutter", "message"],
       "What would you remove from a dashboard that feels crowded?")
_skill("Statistics", ["statistics", "statistical analysis", "descriptive statistics", "hypothesis testing", "regression", "correlation", "standard deviation", "probability", "a/b testing"],
       ["Data analysis"],
       "Explain a statistic in plain words, with a business example, not a formula.",
       "What is the difference between correlation and causation? Give an example from business data.",
       ["correlation", "causation", "third factor", "experiment", "example", "evidence"],
       "How would you test whether a new offer really increased sales?")

# ---- Business ----
_skill("Requirements gathering", ["requirements gathering", "requirement gathering", "requirements analysis", "business requirements", "requirements elicitation", "brd", "user stories", "user story", "acceptance criteria", "use cases"],
       ["Documentation", "Stakeholder management"],
       "Show a method: ask why, confirm in writing, agree acceptance criteria.",
       "How would you gather requirements from a stakeholder who only says they want a better report?",
       ["ask", "why", "goal", "examples", "acceptance criteria", "confirm", "priority"],
       "How do you handle two stakeholders who want conflicting things?")
_skill("Documentation", ["documentation", "technical writing", "process documentation", "sop", "sops", "user guides", "process maps", "process mapping", "flowcharts", "confluence"],
       ["Requirements gathering", "Communication"],
       "Say who reads your documents and how you keep them short, current and easy to find.",
       "What makes a requirements or process document useful for the people who read it?",
       ["audience", "clear", "structure", "version", "examples", "up to date"],
       "How do you make sure people actually read and use your documents?")
_skill("Stakeholder management", ["stakeholder management", "stakeholder engagement", "stakeholder communication", "client management", "managing stakeholders", "stakeholders"],
       ["Communication", "Requirements gathering"],
       "Give an example of a stakeholder you won over: what they needed and what you did.",
       "How do you keep stakeholders informed and aligned during a project?",
       ["updates", "expectations", "regular", "concerns", "agree", "transparent"],
       "What would you do if a senior stakeholder keeps changing their mind?")
_skill("Project planning", ["project planning", "project management", "project schedule", "gantt", "gantt chart", "milestones", "work breakdown", "scope management", "scrum", "agile", "kanban"],
       ["Time management", "Risk management"],
       "Walk through a plan: goal, tasks, owners, dates, dependencies.",
       "How would you plan a small project from the first day to delivery?",
       ["scope", "tasks", "owners", "deadline", "dependencies", "milestones", "review"],
       "What do you do when one task finishes late and others depend on it?")
_skill("Time management", ["time management", "prioritisation", "prioritization", "meeting deadlines", "task prioritization", "multitasking", "deadline management"],
       ["Project planning"],
       "Name your method for prioritising: urgency, impact, then a realistic daily plan.",
       "How do you decide what to work on first when everything seems urgent?",
       ["priority", "urgent", "important", "deadline", "plan", "communicate"],
       "How do you tell your manager that a deadline is at risk?")
_skill("Teamwork", ["teamwork", "team player", "collaboration", "collaborative", "cross-functional", "team collaboration", "working in a team"],
       ["Communication", "Leadership"],
       "Prepare a team story in STAR format: situation, task, your action, the result.",
       "What do you think makes a team work well together, and what do you personally contribute?",
       ["trust", "roles", "communication", "support", "feedback", "shared goal"],
       "What do you do when a teammate is not delivering their part?")
_skill("Jira/Trello", ["jira", "trello", "asana", "clickup", "monday.com", "kanban board", "sprint board"],
       ["Project planning"],
       "Describe how you used a board: columns, who updated it, how it helped the team.",
       "How do you use a task board such as Jira or Trello to keep a team organised?",
       ["columns", "status", "assign", "priority", "deadline", "update", "visible"],
       "What do you do when people stop updating the board?")
_skill("Risk management", ["risk management", "risk assessment", "risk register", "risk mitigation", "contingency plan", "issue log"],
       ["Project planning"],
       "Use the pattern: spot the risk early, rate its impact, name an owner and a fallback.",
       "How would you identify and handle risks in a project that has a fixed deadline?",
       ["identify", "likelihood", "impact", "mitigation", "owner", "monitor", "fallback"],
       "Give an example of a risk that is small but still worth tracking.")
_skill("Negotiation", ["negotiation", "negotiating", "deal closing", "closing deals", "contract negotiation", "price negotiation", "objection handling"],
       ["Communication", "Customer service"],
       "Show you prepare: know your limits, understand their needs, aim for a deal both sides keep.",
       "A customer says your price is too high. How do you respond?",
       ["value", "listen", "needs", "options", "compromise", "limit", "long-term"],
       "When would you walk away from a deal?")
_skill("Customer service", ["customer service", "customer support", "customer success", "client support", "after-sales", "client relations", "customer satisfaction", "csat", "help desk", "call center", "call centre"],
       ["Communication", "CRM"],
       "Tell a story about a difficult customer: you listened, solved it, and they stayed.",
       "How do you handle a customer who is angry about a problem that was not your fault?",
       ["listen", "apologise", "empathy", "solution", "follow up", "calm", "ownership"],
       "How do you decide when to escalate a complaint to a manager?")
_skill("CRM", ["crm", "salesforce", "hubspot", "zoho crm", "zoho", "pipedrive", "lead management", "sales pipeline", "lead tracking", "freshsales"],
       ["Customer service", "Excel"],
       "Explain what you record in a CRM and how that helps the next person who contacts the client.",
       "Why does a sales team need a CRM, and what should be recorded after each customer contact?",
       ["contact", "notes", "pipeline", "follow-up", "history", "stage", "report"],
       "How do you keep the CRM accurate when the team is busy?")

# ---- Marketing ----
_skill("Social media marketing", ["social media marketing", "social media", "social media management", "instagram", "facebook", "linkedin marketing", "tiktok", "community management", "social media content"],
       ["Content planning", "Marketing analytics"],
       "Tie every post to a goal: reach, engagement, leads. Mention one result you measured.",
       "How would you grow engagement on a brand's Instagram or Facebook page?",
       ["audience", "content", "consistency", "engagement", "reels", "analytics", "community"],
       "If reach is high but engagement is low, what would you change?")
_skill("Paid ads (Meta/Google)", ["paid ads", "meta ads", "facebook ads", "instagram ads", "google ads", "adwords", "ppc", "pay per click", "paid social", "paid advertising", "ad campaigns", "ads manager"],
       ["Marketing analytics", "Social media marketing"],
       "Explain how you pick audience, budget and creative, and which result tells you an ad works.",
       "How would you set up a small paid campaign on Meta or Google with a limited budget?",
       ["objective", "audience", "budget", "creative", "targeting", "cpc", "conversion", "test"],
       "Your cost per click is rising. What do you check first?")
_skill("Marketing analytics", ["marketing analytics", "google analytics", "ga4", "campaign analytics", "campaign reporting", "conversion rate", "ctr", "roi", "roas", "marketing metrics", "utm"],
       ["Data analysis", "Paid ads (Meta/Google)"],
       "Name the metric that matches the goal, then say what you would change because of it.",
       "Which metrics would you track to tell whether a marketing campaign worked?",
       ["goal", "reach", "ctr", "conversion", "cost", "roi", "compare"],
       "A campaign has many clicks but few sales. What might explain it?")
_skill("Content planning", ["content planning", "content calendar", "content calendars", "content strategy", "editorial calendar", "social media calendar", "content schedule"],
       ["Social media marketing", "Content writing"],
       "Describe your calendar: goals, themes, formats, posting days, and how you review results.",
       "How would you plan a month of content for a small brand?",
       ["goal", "audience", "themes", "calendar", "formats", "schedule", "review"],
       "How do you decide which topics to repeat and which to drop?")
_skill("SEO", ["seo", "search engine optimization", "search engine optimisation", "on-page seo", "off-page seo", "technical seo", "backlinks", "link building", "meta tags", "serp", "google search console", "semrush", "ahrefs"],
       ["Keyword research", "Content writing"],
       "Explain SEO as three parts: content that answers the search, a healthy site, and trust from links.",
       "What would you do to help a new blog post rank for a search term?",
       ["keyword", "title", "meta description", "headings", "links", "intent", "quality"],
       "How long before you expect to see results, and how do you check progress?")
_skill("Canva", ["canva", "canva pro", "social media graphics", "graphic templates", "design templates", "adobe express"],
       ["Visual design", "Social media marketing"],
       "Show you keep a consistent look: brand colours, fonts and reusable templates.",
       "How do you keep social posts looking consistent when you design them quickly?",
       ["brand", "colours", "fonts", "templates", "layout", "logo", "consistent"],
       "How do you pick an image that fits the message of a post?")
_skill("Content writing", ["content writing", "copywriting", "blog writing", "blog posts", "article writing", "web copy", "content creation", "copywriter", "creative writing", "ghostwriting"],
       ["SEO", "Editing"],
       "Bring one piece you wrote and explain the reader, the goal and why you opened the way you did.",
       "How do you start writing a blog post for a topic you do not know well?",
       ["research", "audience", "outline", "sources", "tone", "headline", "edit"],
       "How do you make a dry topic interesting?")
_skill("Keyword research", ["keyword research", "keyword planner", "keyword analysis", "search volume", "keyword difficulty", "long-tail keywords", "search intent", "keyword mapping"],
       ["SEO", "Marketing analytics"],
       "Explain how you choose keywords: search volume, difficulty and whether it matches what the reader wants.",
       "How do you find and choose keywords for a new page?",
       ["search volume", "difficulty", "intent", "long-tail", "competitors", "relevance", "tools"],
       "Would you choose a high-volume keyword or a low-volume one for a new site, and why?")
_skill("Editing", ["editing", "proofreading", "copy editing", "copyediting", "content editing", "grammarly", "style guide", "fact-checking", "fact checking"],
       ["Content writing"],
       "Describe your checklist: facts, structure, clarity, grammar, tone.",
       "What do you check when you edit someone else's article before it is published?",
       ["facts", "structure", "clarity", "grammar", "tone", "consistency", "feedback"],
       "How do you give an editing note to a writer who is defensive about their work?")
_skill("WordPress", ["wordpress", "wp", "wordpress cms", "elementor", "woocommerce", "wordpress plugins", "yoast"],
       ["SEO", "Content writing"],
       "Mention what you did in WordPress: publishing, plugins, media, SEO settings.",
       "What do you do in a WordPress site to publish a post that is ready for search engines?",
       ["title", "permalink", "categories", "images", "alt text", "plugin", "preview"],
       "What can go wrong when you install too many plugins?")
_skill("Market research", ["market research", "competitor analysis", "competitive analysis", "customer research", "consumer research", "market analysis", "swot", "survey research", "market trends", "industry research"],
       ["Data analysis", "Campaign planning"],
       "Explain the question you wanted answered, the sources you used and what decision came from it.",
       "How would you research a competitor before your company launches a similar product?",
       ["competitor", "pricing", "customers", "strengths", "weaknesses", "sources", "summary"],
       "How do you check that the information you found is reliable?")
_skill("Campaign planning", ["campaign planning", "marketing campaign", "marketing campaigns", "campaign management", "campaign strategy", "campaigns", "marketing plan", "marketing strategy", "product launch", "event marketing"],
       ["Market research", "Marketing analytics"],
       "Walk through a plan: goal, audience, message, channels, budget, timeline, measurement.",
       "How would you plan a campaign to launch a new product on a small budget?",
       ["goal", "audience", "message", "channels", "budget", "timeline", "measure"],
       "How do you decide which channel gets the most budget?")

# ---- HR & Finance ----
_skill("Recruitment", ["recruitment", "talent acquisition", "recruiting", "sourcing", "candidate screening", "screening candidates", "cv screening", "headhunting", "shortlisting", "applicant tracking", "ats", "hiring process", "interview scheduling"],
       ["Onboarding", "Communication"],
       "Explain a hiring pipeline stage by stage and how you keep candidates informed.",
       "How would you design a fair screening process for an entry-level role?",
       ["criteria", "structured", "bias", "shortlist", "interview", "consistent"],
       "How would you check that the process was fair after a hiring round?")
_skill("Communication", ["communication", "communication skills", "verbal communication", "written communication", "presentation", "presentation skills", "public speaking", "email writing", "business communication", "interpersonal skills"],
       ["Teamwork", "Stakeholder management"],
       "Answer in three parts: headline, one example, the result. Keep sentences short.",
       "How would you explain a complicated topic from your field to someone with no background in it?",
       ["audience", "simple", "example", "check understanding", "structure", "avoid jargon"],
       "How do you know the other person really understood you?")
_skill("Onboarding", ["onboarding", "employee onboarding", "new hire orientation", "induction", "orientation program", "new joiner", "joining formalities"],
       ["Recruitment", "HR policies & labour law basics"],
       "Describe what a new employee needs on day one, in the first week and in the first month.",
       "What would you include in an onboarding plan for a new employee's first week?",
       ["welcome", "documents", "equipment", "introductions", "training", "buddy", "feedback"],
       "How do you find out if the onboarding worked?")
_skill("HR policies & labour law basics", ["hr policies", "hr policy", "labour law", "labor law", "employment law", "employee handbook", "leave policy", "code of conduct", "disciplinary procedure", "eobi", "employment contract", "employment contracts"],
       ["Onboarding", "Conflict resolution"],
       "Be honest about your level: explain the basics clearly and say you check the current law for details.",
       "Why does a company need written HR policies, and how do you make sure staff follow them?",
       ["written", "fair", "consistent", "communicate", "acknowledge", "legal", "review"],
       "What do you do when a manager asks you to make an exception to a policy?")
_skill("HRMS tools", ["hrms", "hris", "hr software", "hr systems", "bamboohr", "zoho people", "sap successfactors", "workday", "oracle hcm", "employee database", "hr database"],
       ["Payroll processing", "Excel"],
       "Name the system you used and which task it handled: records, leave, attendance or payroll.",
       "What are the benefits of keeping employee records in an HR system instead of spreadsheets?",
       ["accuracy", "central", "access", "reports", "security", "audit", "time"],
       "How do you protect employee data in such a system?")
_skill("Conflict resolution", ["conflict resolution", "conflict management", "dispute resolution", "mediation", "mediating", "grievance handling", "employee relations", "de-escalation"],
       ["Communication", "Teamwork"],
       "Show a calm sequence: listen to both sides, find the real issue, agree on next steps.",
       "Two employees on your team are in a dispute. How would you help resolve it?",
       ["listen", "both sides", "facts", "neutral", "agreement", "follow up", "confidential"],
       "When would you involve a manager or HR head?")
_skill("Accounting", ["accounting", "accounts payable", "accounts receivable", "general ledger", "ledger", "journal entries", "trial balance", "financial statements", "balance sheet", "double entry", "ifrs", "gaap", "accrual"],
       ["Bookkeeping & reconciliation", "Financial reporting"],
       "Explain the accounting equation and one journal entry from a real transaction.",
       "What is the difference between a debit and a credit, and how do they affect assets and expenses?",
       ["debit", "credit", "assets", "liabilities", "double entry", "balance", "ledger"],
       "How do you check that a trial balance balances?")
_skill("Bookkeeping & reconciliation", ["bookkeeping", "book keeping", "bank reconciliation", "reconciliation", "reconciling accounts", "cash book", "petty cash", "daily vouchers", "voucher entry", "record keeping"],
       ["Accounting", "Attention to detail"],
       "Walk through a bank reconciliation: statement, ledger, the difference, and how you cleared it.",
       "How would you approach a bank reconciliation that does not balance?",
       ["statement", "ledger", "difference", "timing", "error", "adjust"],
       "What are common causes of timing differences?")
_skill("Taxation basics (FBR)", ["fbr", "federal board of revenue", "income tax", "sales tax", "withholding tax", "tax return", "tax returns", "tax filing", "ntn", "iris", "taxation", "tax compliance", "gst"],
       ["Accounting", "Payroll processing"],
       "State what you have done (filing, withholding, records) and be clear about what you would check with a senior.",
       "What do you need to prepare before filing a company's tax return with the FBR?",
       ["records", "income", "expenses", "withholding", "deadline", "documents", "ntn", "accuracy"],
       "What risks does a company face if it files late or incorrectly?")
_skill("QuickBooks/Tally", ["quickbooks", "tally", "tally erp", "tally prime", "xero", "sage", "zoho books", "accounting software", "peachtree", "odoo accounting"],
       ["Accounting", "Bookkeeping & reconciliation"],
       "Name the software and the tasks you did in it: invoices, vouchers, reports.",
       "What are the advantages of using accounting software instead of recording everything by hand?",
       ["accuracy", "reports", "automation", "audit trail", "time", "invoices", "errors"],
       "What checks do you still do yourself after entering data in the software?")
_skill("Attention to detail", ["attention to detail", "detail-oriented", "detail oriented", "accuracy", "data accuracy", "error checking", "quality checks", "meticulous"],
       ["Bookkeeping & reconciliation", "Editing"],
       "Give a real example of an error you caught, how you caught it and what it would have cost.",
       "What habits do you use to avoid mistakes when you work with numbers or records?",
       ["double-check", "checklist", "review", "verify", "totals", "compare", "slow down"],
       "Tell me about a mistake that got through and what you changed afterwards.")
_skill("Financial analysis", ["financial analysis", "ratio analysis", "financial ratios", "variance analysis", "financial statement analysis", "profitability analysis", "cash flow analysis", "budget analysis", "cost analysis"],
       ["Financial reporting", "Financial modelling"],
       "Pick two or three ratios, say what each shows, and give a conclusion a manager can use.",
       "How would you judge from financial statements whether a company is in good health?",
       ["profit", "liquidity", "debt", "cash flow", "ratio", "trend", "compare"],
       "Which one number would you look at first, and why?")
_skill("Financial modelling", ["financial modelling", "financial modeling", "financial forecasting", "forecasting", "forecast", "budgeting", "scenario analysis", "sensitivity analysis", "dcf", "projections"],
       ["Financial analysis", "Excel"],
       "Explain the assumptions first, then how the numbers change when an assumption changes.",
       "How do you build a simple forecast for next year's revenue and costs?",
       ["assumptions", "historical", "growth", "costs", "scenarios", "review", "inputs"],
       "How do you decide which assumption to test first?")
_skill("Financial reporting", ["financial reporting", "management reports", "monthly reports", "mis reports", "mis reporting", "income statement", "profit and loss", "p&l", "cash flow statement", "month-end close", "month end"],
       ["Accounting", "Financial analysis"],
       "Describe a report you prepared: who read it, how often, and what decision it supported.",
       "What goes into a monthly financial report for management, and how do you make it easy to read?",
       ["income", "expenses", "profit", "balance", "variance", "summary", "deadline"],
       "How do you explain an unexpected variance to a manager?")
_skill("Power BI", ["power bi", "powerbi", "power bi desktop", "power query", "dax", "power bi dashboards"],
       ["Data visualization (Power BI/Tableau)", "Excel"],
       "Explain one report: data source, how you cleaned it, which visuals you used and what it showed.",
       "How would you use Power BI to show a manager monthly revenue by region?",
       ["data source", "clean", "measure", "visual", "filter", "region", "refresh"],
       "How do you keep a report accurate when the data changes every day?")
_skill("Payroll processing", ["payroll", "payroll processing", "salary processing", "salary sheet", "salary sheets", "payslip", "payslips", "salary calculation", "payroll software", "wages", "salary disbursement"],
       ["Attendance & leave management", "Taxation basics (FBR)"],
       "Walk through a pay run: attendance, earnings, deductions, tax, approval, payment.",
       "What steps would you follow to process monthly salaries accurately?",
       ["attendance", "gross", "deductions", "tax", "approval", "payslip", "verify"],
       "What would you do if you find a salary error after payment?")
_skill("Attendance & leave management", ["attendance", "attendance management", "leave management", "leave records", "leave balance", "leave tracking", "timesheets", "timesheet", "biometric attendance", "shift scheduling", "overtime"],
       ["Payroll processing", "HRMS tools"],
       "Explain how you track attendance and leave and how errors are fixed before payroll closes.",
       "How would you keep attendance and leave records accurate for a team of 100 people?",
       ["records", "approval", "policy", "balance", "verify", "report", "deadline"],
       "How do you deal with a dispute about a missing attendance entry?")
_skill("Leadership", ["leadership", "team leadership", "team lead", "team leader", "mentoring", "mentor", "led a team", "supervising", "supervision", "people management"],
       ["Teamwork", "Time management"],
       "Prepare one story where you took ownership and say what changed because of it.",
       "What do you think a good leader does differently from a good individual worker?",
       ["direction", "delegate", "support", "feedback", "example", "responsibility"],
       "How do you lead someone who is more experienced than you?")

SKILLS = [(name, v[0], v[1], v[2]) for name, v in _S.items()]

# (id, skill, type, text, keywords, follow_up): one technical question per skill ...
QUESTIONS = [
    (f"{slug(name)}-t1", name, "technical", v[3], v[4], v[5]) for name, v in _S.items()
]

# ... plus shared behavioural questions (any role can be asked these).
_BEHAVIOURAL = [
    ("Communication", [
        ("Tell me about yourself and the strengths you would bring to this role.",
         ["experience", "project", "skill", "team", "learned"],
         "Which one of those strengths has made the biggest difference in a project, and how?"),
        ("Describe a time you had to explain something difficult to someone who did not understand it. What did you do?",
         ["situation", "simple", "example", "checked", "result"],
         "What would you do differently next time?"),
    ]),
    ("Teamwork", [
        ("Tell me about a time you disagreed with a teammate. How did you resolve it?",
         ["listened", "agreed", "compromise", "discussed", "outcome"],
         "Looking back, what would you do differently in that disagreement?"),
        ("Describe a team project where you had to depend on others. What was your part and how did it go?",
         ["role", "shared", "deadline", "supported", "result"],
         "How did you handle a teammate who was behind schedule?"),
    ]),
    ("Problem solving", [
        ("Describe a difficult problem you solved. What was the situation and what did you do?",
         ["problem", "steps", "tested", "result", "cause"],
         "How did you confirm that your solution actually fixed the problem?"),
        ("Tell me about a time something went wrong at work or university and you had to find a fix quickly.",
         ["situation", "options", "decision", "action", "result"],
         "What did you learn that helps you today?"),
    ]),
    ("Time management", [
        ("Tell me about a time you had several deadlines at once. How did you manage them?",
         ["priority", "plan", "deadline", "communicated", "result"],
         "Was there anything you had to let go of, and how did you decide?"),
        ("Describe a time you were running late on a task. What did you do?",
         ["noticed", "told", "adjusted", "help", "delivered"],
         "How do you stop the same delay from happening again?"),
    ]),
    ("Leadership", [
        ("Tell me about a time you took the lead on something without being asked.",
         ["initiative", "team", "plan", "result", "responsibility"],
         "How did the rest of the team respond to you taking the lead?"),
        ("Describe a time you helped a colleague improve or learn something new.",
         ["situation", "supported", "feedback", "patience", "result"],
         "How did you know your help worked?"),
    ]),
]
QUESTIONS += [
    (f"b-{slug(skill)}-{i}", skill, "behavioral", text, keywords, follow_up)
    for skill, items in _BEHAVIOURAL
    for i, (text, keywords, follow_up) in enumerate(items, start=1)
]

OLD_DEMO_QUESTION_IDS = [f"q{i}" for i in range(1, 19)]


def apply(db: Session) -> dict:
    """Upserts the configuration. Does not commit. Returns counts for the report."""
    report = {"domains": 0, "skills_added": 0, "skills_updated": 0, "skills_deleted": [], "skills_kept": [],
              "roles_added": 0, "roles_updated": 0, "roles_inactive": [], "roles_kept_active": [],
              "questions_added": 0, "questions_updated": 0, "questions_removed": 0}

    # domains: by id, falling back to name
    for id_, name in DOMAINS:
        domain = db.get(Domain, id_) or db.scalars(select(Domain).where(func.lower(Domain.name) == name.lower())).first()
        if domain is None:
            db.add(Domain(id=id_, name=name))
            report["domains"] += 1
        else:
            domain.name = name
    db.flush()
    domain_id = {name: (db.scalars(select(Domain.id).where(Domain.name == name)).one()) for _, name in DOMAINS}
    domain_by_key = {key: domain_id[name] for key, name in DOMAINS}

    # skills: by name
    existing = {s.name.lower(): s for s in db.scalars(select(Skill))}
    by_name: dict[str, Skill] = {}
    for name, aliases, related, tip in SKILLS:
        skill = existing.get(name.lower())
        if skill is None:
            skill = Skill(id=slug(name), name=name, aliases=aliases, related=related, tip=tip)
            if db.get(Skill, skill.id) is not None:  # id taken by a skill with another name
                raise RuntimeError(f"Skill id {skill.id!r} is already used by a different skill.")
            db.add(skill)
            report["skills_added"] += 1
        else:
            skill.name, skill.aliases, skill.related, skill.tip = name, aliases, related, tip
            report["skills_updated"] += 1
        by_name[name] = skill
    db.flush()

    # roles: by title (case-insensitive), else by id
    wanted_ids = set()
    for id_, title, key, skills, duties in ROLES:
        role = db.scalars(select(JobRole).where(func.lower(JobRole.title) == title.lower())).first() or db.get(JobRole, id_)
        if role is None:
            role = JobRole(id=id_, title=title, domain_id=domain_by_key[key])
            db.add(role)
            report["roles_added"] += 1
        else:
            report["roles_updated"] += 1
        role.title, role.domain_id, role.responsibilities, role.active = title, domain_by_key[key], duties, True
        db.flush()
        wanted = {by_name[s].id: w for s, w in skills}
        for link in db.scalars(select(RoleSkill).where(RoleSkill.role_id == role.id)).all():
            if link.skill_id in wanted:
                link.weight = wanted.pop(link.skill_id)
            else:
                db.delete(link)
        db.add_all(RoleSkill(role_id=role.id, skill_id=sid, weight=w) for sid, w in wanted.items())
        wanted_ids.add(role.id)
    db.flush()

    # old roles: inactive, never deleted. A role that a job still uses is left active.
    for role in db.scalars(select(JobRole).where(JobRole.id.notin_(wanted_ids))):
        used = db.scalar(select(func.count()).select_from(Job).where(Job.role_id == role.id))
        if used:
            report["roles_kept_active"].append(role.title)
        elif role.active:
            role.active = False
            report["roles_inactive"].append(role.title)

    # old demo questions that nobody edited
    for qid in OLD_DEMO_QUESTION_IDS:
        old = db.get(QuestionTemplate, qid)
        if old is not None and old.updated_at == old.created_at:
            db.delete(old)
            report["questions_removed"] += 1
    db.flush()

    # question templates: by id
    for id_, skill, type_, text, keywords, follow_up in QUESTIONS:
        q = db.get(QuestionTemplate, id_)
        if q is None:
            db.add(QuestionTemplate(id=id_, skill_id=by_name[skill].id, type=type_, text=text, keywords=keywords,
                                    follow_up=follow_up, source="admin"))
            report["questions_added"] += 1
        else:
            q.skill_id, q.type, q.text, q.keywords, q.follow_up = by_name[skill].id, type_, text, keywords, follow_up
            report["questions_updated"] += 1
    db.flush()

    # old skills: keep while something uses them, delete otherwise
    keep_ids = {s.id for s in by_name.values()}
    for skill in db.scalars(select(Skill).where(Skill.id.notin_(keep_ids))).all():
        used = (
            db.scalar(select(func.count()).select_from(JobSkill).where(JobSkill.skill_id == skill.id))
            or db.scalar(select(func.count()).select_from(RoleSkill).where(RoleSkill.skill_id == skill.id))
            or db.scalar(select(func.count()).select_from(SessionAnswer).where(SessionAnswer.skill_id == skill.id))
        )
        if used:
            report["skills_kept"].append(skill.name)
        else:
            db.delete(skill)  # its question templates go with it (ON DELETE CASCADE)
            report["skills_deleted"].append(skill.name)
    return report


def main() -> None:
    with SessionLocal() as db:
        report = apply(db)
        db.commit()
    print(f"Domains added: {report['domains']}")
    print(f"Skills: {report['skills_added']} added, {report['skills_updated']} updated")
    print(f"Roles: {report['roles_added']} added, {report['roles_updated']} updated")
    print(f"Questions: {report['questions_added']} added, {report['questions_updated']} updated, "
          f"{report['questions_removed']} old demo questions removed")
    for label, key in [("Old skills deleted (unused)", "skills_deleted"), ("Old skills kept (still used)", "skills_kept"),
                       ("Old roles marked inactive", "roles_inactive"), ("Old roles kept active (jobs use them)", "roles_kept_active")]:
        if report[key]:
            print(f"{label}: {', '.join(report[key])}")


if __name__ == "__main__":
    main()
