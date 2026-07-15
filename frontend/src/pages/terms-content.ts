/**
 * terms-content.ts — Authoritative text for Celo Trader Terms of Service v1.0
 *
 * LEGAL NOTE: This document was drafted with reference to:
 *   • SEC Investment Advisers Act of 1940
 *   • Securities Exchange Act of 1934 (Section 15)
 *   • CFTC Rule 4.41 (hypothetical performance disclosures)
 *   • SEC Rule 156 (past performance in investment company literature)
 *   • FINRA Regulatory Notice 16-21 (algorithmic trading supervision)
 *
 * Attorney review recommended before deploying to users in additional jurisdictions.
 *
 * To re-prompt all users after a text change: bump CURRENT_TERMS_VERSION in
 * auth/users.py from "1.0" to "1.1" (or higher).
 */

export interface TermsSection {
  id:       string;
  heading:  string;
  body:     string;
  allCaps?: boolean;   // true → render in uppercase (CFTC/SEC required blocks)
}

export const TERMS_VERSION = "1.1";
export const TERMS_DATE    = "July 2026";

export const SECTIONS: TermsSection[] = [
  {
    id: "definitions",
    heading: "1. Definitions",
    body:
      '"Software" means Celo Trader, its source code, compiled binaries, web interface, ' +
      'APIs, algorithms, and all associated documentation. "You" or "User" means any ' +
      'individual or entity that accesses or operates the Software. "Operator" means the ' +
      'party that hosts and distributes the Software. "Brokerage Account" means any ' +
      'third-party account you own and use in connection with the Software.',
  },
  {
    id: "not-registered",
    heading: "2. Not an Investment Adviser or Broker-Dealer",
    body:
      'The Operator is NOT registered as an investment adviser under the Investment Advisers ' +
      'Act of 1940, is NOT registered as a broker-dealer under Section 15 of the Securities ' +
      'Exchange Act of 1934, and is NOT a member of FINRA or any self-regulatory organization. ' +
      'The Software does not provide investment advice, portfolio management, securities ' +
      'recommendations, or brokerage services. No communication from the Software constitutes ' +
      'a solicitation or offer to buy or sell any security. Nothing herein creates a ' +
      'broker-client or adviser-client relationship of any kind.',
  },
  {
    id: "educational",
    heading: "3. Educational and Informational Purposes Only",
    body:
      'All signals, strategy outputs, analytics, backtest results, and other information ' +
      'generated or displayed by the Software are provided solely for educational and ' +
      'informational purposes. They are not tailored to your individual investment objectives, ' +
      'financial situation, risk tolerance, or tax circumstances. You should consult a ' +
      'licensed financial adviser, attorney, and/or tax professional before making any ' +
      'financial or investment decision.',
  },
  {
    id: "past-performance",
    heading: "4. Past Performance & Hypothetical Results",
    body:
      'Past performance — whether live, paper-traded, or backtested — is NOT indicative of ' +
      'future results. No representation is made that any account will or is likely to ' +
      'achieve profits or losses similar to those shown. In accordance with CFTC Rule 4.41:',
  },
  {
    id: "cftc-block",
    heading: "",   // rendered inline under section 4
    allCaps: true,
    body:
      'HYPOTHETICAL OR SIMULATED PERFORMANCE RESULTS HAVE CERTAIN LIMITATIONS. UNLIKE AN ' +
      'ACTUAL PERFORMANCE RECORD, SIMULATED RESULTS DO NOT REPRESENT ACTUAL TRADING. ALSO, ' +
      'SINCE THE TRADES HAVE NOT BEEN EXECUTED, THE RESULTS MAY HAVE UNDER-OR-OVER ' +
      'COMPENSATED FOR THE IMPACT, IF ANY, OF CERTAIN MARKET FACTORS, SUCH AS LACK OF ' +
      'LIQUIDITY. SIMULATED TRADING PROGRAMS IN GENERAL ARE ALSO SUBJECT TO THE FACT THAT ' +
      'THEY ARE DESIGNED WITH THE BENEFIT OF HINDSIGHT. IN ADDITION, HYPOTHETICAL TRADING ' +
      'DOES NOT INVOLVE FINANCIAL RISK, AND NO HYPOTHETICAL TRADING RECORD CAN COMPLETELY ' +
      'ACCOUNT FOR THE IMPACT OF FINANCIAL RISK IN ACTUAL TRADING. NO REPRESENTATION IS ' +
      'BEING MADE THAT ANY ACCOUNT WILL OR IS LIKELY TO ACHIEVE PROFIT OR LOSSES SIMILAR ' +
      'TO THOSE SHOWN.',
  },
  {
    id: "risk-disclosure",
    heading: "5. Risk Disclosure — Material Risks of Automated Options Trading",
    body:
      'Options trading involves substantial risk and is not appropriate for all investors. ' +
      'You may lose your entire invested capital. Only "risk capital" — money you can afford ' +
      'to lose in its entirety — should be used. Specific risks include, without limitation: ' +
      '(a) Market Risk: rapid, unpredictable price movements may cause losses in excess of ' +
      'your initial position; (b) Liquidity Risk: options may be illiquid, causing wide ' +
      'bid-ask spreads or inability to exit; (c) Algorithmic Risk: software bugs, logic ' +
      'errors, or unanticipated market conditions may cause the Software to behave ' +
      'unexpectedly; (d) Connectivity Risk: internet outages, API rate limits, or latency ' +
      'may prevent timely order execution; (e) Execution Risk: orders may be filled at prices ' +
      'materially different from expected; (f) System Failure Risk: the Software may ' +
      'experience downtime, crashes, or data errors; (g) Third-Party Risk: failures of ' +
      'Alpaca, Tradier, or any other connected service are outside the Operator\'s control. ' +
      'You acknowledge that you have carefully considered these risks and that automated ' +
      'trading is not suitable for most retail investors.',
  },
  {
    id: "brokerage",
    heading: "6. Your Brokerage Account — Your Sole Responsibility",
    body:
      'You own and control your Brokerage Account exclusively. You are solely responsible ' +
      'for: (a) ensuring you have read and accepted your broker\'s terms of service; ' +
      '(b) all trading activity, whether initiated by the Software or manually; ' +
      '(c) compliance with your broker\'s policies on automated trading; (d) maintaining ' +
      'sufficient margin and capital; and (e) any losses, margin calls, or account ' +
      'restrictions resulting from the Software\'s activity. The Operator does not hold, ' +
      'transmit, custody, or have access to your funds or brokerage credentials.',
  },
  {
    id: "third-party",
    heading: "7. Third-Party Services",
    body:
      'The Software connects to third-party services including, but not limited to, Alpaca ' +
      'Securities LLC and Tradier Brokerage Inc. (collectively, "Third-Party Services"). ' +
      'These services are operated by independent companies subject to their own terms, ' +
      'privacy policies, and regulatory requirements. The Operator makes no representations ' +
      'as to the availability, accuracy, or reliability of any Third-Party Service. ' +
      'Interruptions, API changes, rate limits, or termination of access by any ' +
      'Third-Party Service may impair or disable the Software without notice. Your use of ' +
      'Third-Party Services is solely at your own risk and subject to each provider\'s ' +
      'governing agreements.',
  },
  {
    id: "fiduciary",
    heading: "8. No Fiduciary Duty",
    body:
      'Nothing in this Agreement or the Software creates a fiduciary, advisory, custodial, ' +
      'or agency relationship between you and the Operator. The Operator owes you no duty ' +
      'of care with respect to any trading decision, financial outcome, or investment ' +
      'result. You bear sole and exclusive responsibility for all trading decisions made ' +
      'in connection with your use of the Software.',
  },
  {
    id: "market-data",
    heading: "9. Market Data Accuracy",
    body:
      'Any market data, pricing, quotes, or financial information displayed or used by the ' +
      'Software is sourced from third parties and may be delayed, inaccurate, or incomplete. ' +
      'The Operator does not guarantee the accuracy, timeliness, or completeness of any ' +
      'market data. You should independently verify all data before making any decision. ' +
      'Data delays or errors may result in missed trades, incorrect signals, or financial loss.',
  },
  {
    id: "warranty",
    heading: "10. No Warranty — Software Provided \"AS-IS\"",
    body:
      'THE SOFTWARE IS PROVIDED "AS IS" AND "AS AVAILABLE" WITHOUT WARRANTY OF ANY KIND, ' +
      'EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO WARRANTIES OF MERCHANTABILITY, ' +
      'FITNESS FOR A PARTICULAR PURPOSE, ACCURACY, TITLE, AND NON-INFRINGEMENT. THE ' +
      'OPERATOR DOES NOT WARRANT THAT THE SOFTWARE WILL BE ERROR-FREE, UNINTERRUPTED, ' +
      'FREE OF BUGS OR DEFECTS, OR THAT ANY DEFECTS WILL BE CORRECTED. THE ENTIRE RISK ' +
      'AS TO THE QUALITY AND PERFORMANCE OF THE SOFTWARE IS WITH YOU.',
  },
  {
    id: "liability",
    heading: "11. Limitation of Liability",
    body:
      'TO THE FULLEST EXTENT PERMITTED BY APPLICABLE LAW, IN NO EVENT SHALL THE OPERATOR, ' +
      'ITS OFFICERS, DIRECTORS, EMPLOYEES, AGENTS, OR AFFILIATES BE LIABLE FOR ANY ' +
      'INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, EXEMPLARY, OR PUNITIVE DAMAGES, ' +
      'INCLUDING WITHOUT LIMITATION LOSS OF PROFITS, LOSS OF CAPITAL, LOSS OF DATA, OR ' +
      'LOSS OF BUSINESS, ARISING OUT OF OR IN CONNECTION WITH YOUR USE OR INABILITY TO ' +
      'USE THE SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGES. THE ' +
      'OPERATOR\'S MAXIMUM AGGREGATE LIABILITY TO YOU FOR ANY CLAIM ARISING OUT OF THIS ' +
      'AGREEMENT SHALL NOT EXCEED THE GREATER OF (A) THE TOTAL FEES PAID BY YOU FOR THE ' +
      'SOFTWARE IN THE TWELVE (12) MONTHS PRECEDING THE CLAIM, OR (B) ONE HUNDRED DOLLARS ' +
      '($100). SOME JURISDICTIONS DO NOT ALLOW THE EXCLUSION OF CERTAIN WARRANTIES OR THE ' +
      'LIMITATION OF LIABILITY FOR CONSEQUENTIAL DAMAGES; IN SUCH JURISDICTIONS, THE ' +
      'OPERATOR\'S LIABILITY IS LIMITED TO THE GREATEST EXTENT PERMITTED BY LAW.',
  },
  {
    id: "indemnification",
    heading: "12. Indemnification",
    body:
      'You agree to indemnify, defend, and hold harmless the Operator and its officers, ' +
      'directors, employees, agents, licensors, and affiliates from and against any and all ' +
      'claims, liabilities, damages, losses, costs, and expenses (including reasonable ' +
      'attorneys\' fees) arising out of or relating to: (a) your use of the Software; ' +
      '(b) any trading activity in your Brokerage Account; (c) your violation of this ' +
      'Agreement; (d) your violation of any applicable law or regulation; or (e) any ' +
      'third-party claim arising from your conduct.',
  },
  {
    id: "tax",
    heading: "13. Tax Obligations",
    body:
      'You are solely responsible for determining and fulfilling all tax obligations ' +
      'arising from your trading activity, including but not limited to capital gains ' +
      'taxes, wash-sale rule implications, and any reporting requirements under applicable ' +
      'federal, state, or local law. The Software does not provide tax advice. The Operator ' +
      'bears no liability for any tax consequences arising from your use of the Software.',
  },
  {
    id: "geographic",
    heading: "14. Geographic Restrictions",
    body:
      'The Software is intended for use in the United States only. The Operator makes no ' +
      'representation that the Software is appropriate or legally permissible in any other ' +
      'jurisdiction. If you access or use the Software from outside the United States, you ' +
      'do so at your own risk and are solely responsible for compliance with all applicable ' +
      'local laws and regulations, including any restrictions on automated trading, securities ' +
      'activity, or software of this type.',
  },
  {
    id: "governing-law",
    heading: "15. Governing Law, Dispute Resolution & Class Action Waiver",
    body:
      'This Agreement shall be governed by and construed in accordance with the laws of the ' +
      'State of Maryland, USA, without regard to its conflict of laws provisions. Any dispute ' +
      'arising out of or relating to this Agreement shall be resolved by binding arbitration ' +
      'administered by the American Arbitration Association (AAA) under its Commercial ' +
      'Arbitration Rules, with proceedings conducted in English in the State of Maryland. ' +
      'YOU WAIVE ANY RIGHT TO PARTICIPATE IN A CLASS ACTION LAWSUIT OR CLASS-WIDE ' +
      'ARBITRATION AGAINST THE OPERATOR. Notwithstanding the foregoing, either party may ' +
      'seek emergency injunctive relief from a court of competent jurisdiction.',
  },
  {
    id: "modifications",
    heading: "16. Modification of Terms",
    body:
      'The Operator reserves the right to modify these Terms at any time. When material ' +
      'changes are made, you will be required to re-accept the updated Terms before ' +
      'continuing to use the Software. Continued use after acceptance constitutes your ' +
      'agreement to the revised Terms. It is your responsibility to review the Terms ' +
      'periodically.',
  },
  {
    id: "service-availability",
    heading: "17. Service Availability and Scheduled Maintenance",
    body:
      'The Operator reserves the right to suspend, restrict, or take the Software offline at ' +
      'any time and for any duration, including for scheduled maintenance, emergency repairs, ' +
      'security patches, infrastructure upgrades, regulatory compliance reviews, or when the ' +
      'Software\'s trading performance falls below acceptable thresholds and maintenance is ' +
      'required to investigate or remediate issues. The Operator will make reasonable efforts ' +
      'to provide advance notice of planned downtime where practicable, but is under no ' +
      'obligation to do so. Downtime — whether planned or unplanned — may result in missed ' +
      'trade signals, open positions that cannot be managed by the Software, or loss of ' +
      'connectivity to your Brokerage Account. You agree that the Operator shall not be ' +
      'liable for any financial loss, missed opportunity, or adverse trading outcome resulting ' +
      'from any period of Software downtime, maintenance, or suspension, regardless of cause. ' +
      'You are solely responsible for monitoring your open positions and Brokerage Account ' +
      'during any period of Software downtime.',
  },
  {
    id: "no-refund",
    heading: "18. No Refund Policy",
    allCaps: false,
    body:
      'ALL PAYMENTS MADE FOR ACCESS TO THE SOFTWARE ARE FINAL AND NON-REFUNDABLE. This ' +
      'includes, without limitation: fees paid during periods of Software downtime, outage, ' +
      'or reduced functionality; fees paid during periods when the Software experienced trading ' +
      'losses, missed signals, or performed below your expectations; fees paid during periods ' +
      'of scheduled or unscheduled maintenance; fees paid for any subscription period in which ' +
      'you chose not to use the Software; and any fees paid prior to a decision to stop using ' +
      'the Software. The Operator does not offer credits, refunds, or fee adjustments for any ' +
      'reason, including but not limited to trading losses, bot failures, connectivity issues, ' +
      'third-party service outages, or dissatisfaction with performance. By purchasing access ' +
      'to the Software, you acknowledge that trading results are inherently uncertain and that ' +
      'the Software\'s failure to generate profits — or its generation of losses — does not ' +
      'entitle you to any refund of fees paid. If you have questions about billing, contact ' +
      'support before purchasing.',
  },
  {
    id: "miscellaneous",
    heading: "19. Miscellaneous",
    body:
      'Severability: If any provision of this Agreement is held invalid or unenforceable, ' +
      'the remaining provisions shall remain in full force. Entire Agreement: This Agreement ' +
      'constitutes the entire agreement between you and the Operator regarding the Software ' +
      'and supersedes all prior understandings. No Waiver: Failure to enforce any provision ' +
      'shall not constitute a waiver of future enforcement rights. No Assignment: You may ' +
      'not assign your rights or obligations under this Agreement without the Operator\'s ' +
      'prior written consent. Force Majeure: The Operator shall not be liable for any ' +
      'failure or delay caused by circumstances beyond its reasonable control, including ' +
      'market halts, exchange outages, internet disruptions, natural disasters, or ' +
      'government actions.',
  },
];
