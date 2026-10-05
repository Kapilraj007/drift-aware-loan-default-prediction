import { Card, Descriptions, Steps, Typography } from "antd";
import { PageIntro } from "../components/Page";

const lifecycle = [
  { title: "Application", description: "Validated applicant, loan, and credit fields." },
  { title: "Score", description: "A versioned model estimates default risk." },
  { title: "Explanation", description: "The assigned study view may show top contributors." },
  { title: "Human decision", description: "A qualified officer approves, declines, or escalates." },
  { title: "Monitoring", description: "ADWIN and KS evidence track changing distributions." },
  { title: "Retraining review", description: "People review evidence; approval never trains automatically." },
];

const glossary = [
  { key: "risk", label: "Default risk", children: "The model's estimated probability that the loan defaults. It is not a lending decision." },
  { key: "threshold", label: "Threshold", children: "The score boundary used to flag applications for closer review." },
  { key: "dti", label: "DTI", children: "Debt-to-income ratio: recurring debt payments relative to income." },
  { key: "shap", label: "SHAP", children: "A local explanation of which model inputs pushed one score higher or lower." },
  { key: "ks", label: "KS test", children: "A statistical comparison of one numeric feature across reference and current cohorts." },
  { key: "adwin", label: "ADWIN", children: "An online detector that watches the stream of model scores for change." },
  { key: "drift", label: "Drift", children: "A change in observed input or score distributions that warrants human investigation." },
  { key: "study", label: "A/B study", children: "A controlled comparison of explanation-shown and score-only review experiences." },
];

export function HowItWorksPage() {
  return <>
    <PageIntro title="How it works" purpose="Follow the complete decision-support lifecycle and learn the terms used across the workspace." />
    <Card title="Application lifecycle">
      <Steps responsive current={-1} items={lifecycle} />
      <Typography.Paragraph className="section-row">
        Every score, decision, amendment, detector snapshot, and ticket review is retained for audit. The model supports judgment; it never makes the final lending decision or retrains itself.
      </Typography.Paragraph>
    </Card>
    <Card className="section-row" title="Plain-language glossary">
      <Descriptions bordered column={{ xs: 1, md: 2 }} items={glossary} />
    </Card>
  </>;
}
