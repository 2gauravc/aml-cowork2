# Discovery Sprint

## Objective

The objective of the Discovery Sprint is to demonstrate a new way of creating a digital workforce.

Using KYC as the business context, the sprint will test if digital workers (agents) can be created faster with a fundamentally different operating model than traditional technology delivery. Rather than treating this as another technology project, the sprint  will evaluate how we can create, maintain and improve digital workers at a radically faster pace - using the modern method of co-creating agents with AI.

The outcome of the Discovery Sprint is more than a KYC agent Proof of Concept. It is a blueprint for how the bank can build and scale a digital workforce. If successful, the new blueprint can be extended beyond KYC - to transform knowledge work across the enterprise.

## Success Criteria

The Discovery Sprint will be considered successful if it demonstrates the following:

### 1. Shift Left Delivery Model

Demonstrate that small teams of 2-4 people, with the KYC CORE team at the forefront, can:
 - Create a meaningful KYC digital worker using an Agent Studio Platform. the Agent will use mock data / documents (to be created by AI) 
 - This can be done in a short time window of 1-2 weeks. The team will minimize dependence on traditional SDLC process by enablig rapid co-cration with AI 

 Objective is to discover what becomes possible when we remove today's delivery assumptions and leverage frontier AI capabiities. 

### 2. Human-by-Exception Decision Model

Demonstrate that digital workers can perform routine KYC activities, enabling humans to focus on judgement, exception handling and on improving the digital workers. 

Discover how far today's fronteir AI can be in doing end to end KYC activities:

1. Which KYC activities can be performed reliably by AI today?
2. Which activities need human judgement? 
3. What activities can be performed by AI with technology / policy evolution ?  
4. What kind of governance is needed to make this work including - explainability, evaluation, audit trail, prompt versioning (and back testing), confidence thresholds and human feedback  

## Proof Scenarios 

The agent will complete a new CDD (onboarding). 

The CDD will have 4 sections.  

1) Customer Business Profile (CBP) 
2) Ownership & Control (OC) 
3) ID&V 
4) Risk Flags 

The CDD output will be produced in standard JSON and also downloadable as PDF. 

### 1. Customer Business Profile (CBP): 
CBP schema fields 
a) commpany name 
b) Biz registration Number 
c) incorporation date 
d) incorporation country (jurisdiction)
e) paid-up capital (amount, currency) 
f) Company Type (e.g. Private Limited), 
g) Registered Address 
h) Company Status (e.g. active, dissolved) 
i) Entity type (e.g. Commercial Corporate) -- TBD
j) Listing status (Listed, NASDAQ) -- TBD
k) Activity  


### 2. Ownership & Control (OC): 
 
OC Schema Fields 
a) UBOs - For each UBO -> Name, effective shareholding %
b) Shareholders > 10%. For each shareholder -> Name, Type (Ind / Company), Effective % Shareholding  
c) Related Parties. These include company officers (Director, Secretary etc.) of:
 - Customer / top-level company
 - Corporate shareholder whose effective ownership in the customer is over 10%.

### 3. ID&V 

 ID&V generates one synthetic identity document for each required UBO and/or director, based on the policy (policies/idv_policy.txt). People are deduplicated, and the document type is currently always the first accepted type in the policy—usually a passport.

1. Identify documents needed 
2. Generate synthetic document 
3. Upload the fake documents 
4. Separate, classify 
5. Match uploaded document (to list of required documents)
6. Extract and populate 

### 4. Red Flags (RF)

The agent will evaluate risk red flags 
a) Shell typology risk, if Paid-Up-Capital < SGD 800 -- TBD
b) Nominee arrangement assessment (including CSP address) 
c) Counterparty and txn declaration assessment  
c) High risk industry flags -- TBD

The output of the Risk Red Flags is: 
1. Clear Red Flgas Identified and explanation / rationale 
2. Considerations - RFI (more information) 
3. Risk rating 
4. Approval Memo 


## Data and Information Available (via Tools)

### From [knowyourcustomer.com sandbox](https://knowyourcustomer.com/developers/sandbox/)


| Tool | KYC API | What it Returns                    |
| ----|----------|------------------------------------|
| get_customer_static_by_name(company_name, jurisdiction)   | GET /v2/Companies/{case_id}           | Company profile: registration details, status, activity, and registered address                                                   |
| get_company_members_by_name(company_name, jurisdiction)   | GET /v2/Companies/{case_id}/members   | Members: directors, secretaries, shareholders, UBOs, addresses                                                                    |
| get_company_org_chart_by_name(company_name, jurisdiction) | GET /v2/Companies/{case_id}/org-chart | Recursive ownership tree: corporate owners, nested shareholders, officers,<br>                    PSCs, and ownership percentages |

### Documents (Fake generated)

The code produces the following fake documents:
1) Company business profile 
2) Individual passport 
3) National ID
4) Counterparty and Transaction declaration -- TBD

Documents are produced on the basis of schema defined. The code then reads the PDF generated. 

### Web Search 

1. Search the address to determine CSP risk (does not apply to synthetic entities)
2. Search the web to identify counterparties (3-5) 
3. Listing search 

### other Data sources (NOT IN SCOPE)

a) Company Profile via Search in a JSON Document. The JSON has fake Web search results 
b) Linkedin Profiles - via Search in a JSON Document. The JSON has fake LInkedIn Profiles 

## SKILLS (to execute a business process without deterministic code)

1. Entity Type in CBP (e.g. Commercial Corporate)
2. Listing status in CBP (Listed, NASDAQ)
3. High risk industry flags in RF 
4. Nominee arrangement assessment in RF (including CSP address) 
5. Counterparty and txn declaration plausibility assessment in RF  
6. Separate and classify documents in ID&V
7. Match uploaded document (to list of required documents) in ID&V
8. Document and Information Gap assessment in ID&V

Other business logic execution via Code (deterministic): 

1. Extract from PDF document according to schema 
2. Shell Typology Risk Detection in RF 

