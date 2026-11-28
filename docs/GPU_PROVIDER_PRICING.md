# GPU provider comparison and price

Prices and terms checked on **28 November 2026** on public web pages. Nobody has been contacted and nothing has been bought. Confirm every figure
in a written quote before paying.

## Summary

| | |
|---|---|
| Need | One server for 10 students at the same time, all day and night, with 24/7 provider support |
| Suggested provider | **AceCloud** (India): 24/7 support included, 99.99% uptime stated, no commitment on monthly plans |
| Expected monthly cost | **About $411 (L4) or $454 (A30)** with 250 GB of extra disk, before 18% GST |
| Cost per student, server always full | About **$0.016 to $0.017** |
| Cost per student at 3,000 tests a month | About **$0.14 to $0.15** |
| Biggest open risk | **None of these servers has been tested with our service.** Our load test was on an RTX 3090 |

## What the server must have

| Requirement | Why |
|---|---|
| 1 NVIDIA GPU with 24 GB | Language model, speech recognition and voice share one card |
| 32 GB RAM or more | Recordings are held in memory until a test ends |
| 250 GB disk or more | Container image, models and 30 days of recordings (see "Disk space") |
| Virtual machine or physical server with root access | We run one Docker container. Rented containers (such as vast.ai) cannot run Docker |
| Docker and NVIDIA Container Toolkit | Starts and restarts the service (`DEPLOY_SERVER.md`) |
| Outbound internet | Downloads models at the first start; the Cloudflare tunnel connects outward |
| 24/7 support | Tests are taken at any hour |

## Monthly cost

Running all month (730 hours), before tax.

| # | Provider and plan | GPU | vCPU / RAM | GPU server | Disk | Support | **Per month** | **Per year** |
|---|---|---|---|---:|---:|---:|---:|---:|
| 1 | AceCloud `N.L4.32` | L4 | 8 / 32 GB | ₹36,730 | ₹1,500 (250 GB) | included | **$411** (₹38,230) | $4,933 |
| 1b | AceCloud `N.A30.32` | A30 | 8 / 32 GB | ₹40,693 | ₹1,500 (250 GB) | included | **$454** (₹42,193) | $5,444 |
| 2 | HostKey `gpu.v3-4090` | RTX 4090 | 12 / 64 GB | €379 | 1 TB included | included | **$415** (€379) | $4,980 |
| 3 | E2E Networks L4 | L4 | 25 / 110 GB | $416 | $25 (250 GB) | included, confirm | **$441** | $5,293 |
| 4 | Google Cloud `g2-standard-8` | L4 | 8 / 32 GB | $649 | about $30 | about $100 | **about $779** | about $9,344 |
| 5 | AWS `g6.2xlarge` | L4 | 8 / 32 GB | $857 | about $23 | 9%, about $79 | **about $959** | about $11,508 |

- Exchange rates used (approximate, 27 November 2026): $1 = ₹93, €1 = $1.095. For taka, multiply the dollar figure by the day's bank rate.
- **AceCloud:** prices are for Noida. With 18% GST: about $485 (L4) and $535 (A30). The size of the included boot disk is not stated, so the table adds 250 GB.
- **E2E:** $0.57 per hour. In rupees: ₹38,270 a month with disk. Taxes excluded.
- **HostKey:** a paid "Top priority" support level adds €50 (total about $470). Prices show 0% VAT for customers outside the EU.
- **Google:** server price is from a third-party site. The disk and support prices are **unconfirmed**: with a $500 support minimum, which some sources report, the total is about $1,179.
- **AWS:** server price is from a third-party site, disk price is an old estimate, support is AWS Business Support+ (the greater of $29 or 9%).

## Cost per student, 10 at a time

A full test takes 13 to 16 minutes. With a 15-minute slot, 10 places give **40 tests an hour**.

**Cost per student = monthly cost / tests in that month**

| Tests a month | Full use needed per day | AceCloud L4 | AceCloud A30 | HostKey 4090 | E2E L4 | Google L4 | AWS L4 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1,000 | about 50 minutes | $0.41 | $0.45 | $0.42 | $0.44 | $0.78 | $0.96 |
| 3,000 | 2.5 hours | $0.14 | $0.15 | $0.14 | $0.15 | $0.26 | $0.32 |
| 10,000 | about 8.3 hours | $0.043 | $0.047 | $0.042 | $0.047 | $0.081 | $0.098 |
| 28,800 | 24 hours | $0.016 | $0.017 | $0.014 | $0.018 | $0.030 | $0.036 |

- At 10,000 tests the disk is counted as 500 GB, and at 28,800 as 1 TB. HostKey already includes 1 TB.
- "Full use" means all 10 places are taken. Real students arrive unevenly, so the real cost per student will be higher at the same opening hours.
- One batch of 10 students costs ten times the figure in the table.
- There is no per-test AI fee: the models run on our server.
- Not included: tax, network traffic, a staging server, the domain, and staff time.

## Features and support

"Not stated" means the pages read did not say. It does not mean the feature is missing.

| | AceCloud | HostKey | E2E Networks | Google Cloud | AWS |
|---|---|---|---|---|---|
| 24 GB NVIDIA GPU | Yes | Yes | Yes | Yes (L4) | Yes (L4) |
| 32 GB RAM or more | Yes | Yes | Yes | Yes | Yes |
| VM or physical server | VM | Dedicated server | VM | VM | VM |
| Root access | Stated | "Depending on configuration" | Not stated | Not checked | Not checked |
| Docker + NVIDIA toolkit | Not stated | Not stated | Not stated | Not checked | Not checked |
| 24/7 support | Yes, included (chat, email, phone) | Yes | Yes on the GPU page; the pricing page lists support levels | Needs a paid plan | Needs a paid plan |
| Stated response time | Not seen | "15 minutes" first response | By level: 24 hours, 4 hours, 1 hour | 1 hour for the most urgent cases (Enhanced) | 30 minutes for critical production issues |
| Uptime stated | 99.99%, GPU instances included | No clear figure for GPU servers | 99.9% | Not checked | 99.5% for a single server |
| Data centre | Noida, Mumbai | Europe, USA and others; none in Asia listed | Delhi NCR, Chennai | Mumbai | Mumbai |
| Who manages the system | Us | Us ("unmanaged") | Us | Us | Us |

Provider support normally covers **their server and network**. Keeping our speaking service running stays our job, so the company still needs a
person who receives outage alerts.

## Which one, and why

| Provider | For | Against |
|---|---|---|
| **AceCloud** (suggested) | Low price, 24/7 support included, highest stated uptime, root access stated, near Bangladesh, no commitment on monthly plans | No hourly price listed for these plans, so a trial may cost a month. Refunds are case by case |
| **HostKey** | Expected to be the fastest GPU in this list, large disk included, low price | No Asian data centre listed, so replies may be slower. Unmanaged. Check that the plan can be ordered now and where it is |
| **E2E Networks** | Billed by the minute, so testing is cheap. Much more RAM | Support terms differ between two of its pages. Monthly price only by quote |
| **Google Cloud** | Large established provider, Mumbai | Nearly twice the price. Support price unconfirmed |
| **AWS** | Large established provider, Mumbai, clear support terms | Highest price. Lower uptime promise for one server |

## Performance warning

Our load test ran on an **RTX 3090** (`GPU_TEST_2026-11-26.md`): it stayed within the delay rule at up to 12 students and not at 16.

| GPU | Expectation (not tested) |
|---|---|
| L4 | Much lower memory bandwidth than the 3090, so it **may not hold 10 students** |
| A30 | Memory bandwidth close to the 3090: likely safer than the L4 |
| RTX 4090 | Expected to be faster than the 3090 |

If a card cannot hold 10, the options are a faster card, a lower `MAX_SESSIONS`, or a second server. All three change the cost per student.

## Disk space

A 15-minute recording is about 29 MB and is kept for 30 days (`RETENTION_DAYS`).

| Tests a month | Recordings kept | Disk to order |
|---:|---:|---|
| 3,000 | about 86 GB | 250 GB |
| 10,000 | about 290 GB | 500 GB |
| 28,800 | about 830 GB | 1 TB or more (tight): shorten retention or compress recordings |

## Next steps

1. Rent an E2E L4 by the minute for a few hours (about $0.57 an hour) and run the 10-student load test. This shows whether an L4 is enough.
2. If it passes, order AceCloud L4. If it fails, ask AceCloud for an A30 trial, or compare with the RTX 4090.
3. Before paying, ask the provider:
   - Do we get root access, and do Docker and NVIDIA Container Toolkit work?
   - Which city is the server in, and is the GPU reserved for us?
   - What does 24/7 support cover, and how fast is the first reply?
   - What are the uptime terms and credits?
   - What do disk, network traffic and tax add for a customer in Bangladesh?
   - Can we cancel monthly, and is there a trial?
4. Test the network delay from Bangladesh.

## Looked at and left out

| Provider | Reason |
|---|---|
| vast.ai and similar container rentals | Cannot run Docker |
| CloudBaseIndia (RTX 4090) | Its page shows a discount label and a refund rule that contradict its other figures, and does not say where this server is |
| Hetzner GEX44 | 20 GB GPU |

## Sources

| Provider | Pages |
|---|---|
| AceCloud (official) | [L4 price](https://acecloud.ai/pricing/linux/inr/noida/nvidia-l4-24gb/), [A30 price](https://acecloud.ai/pricing/linux/inr/noida/nvidia-a30-24gb/), [GPU cloud](https://acecloud.ai/cloud/gpu/), [block storage](https://acecloud.ai/cloud/storage/block/), [FAQ](https://acecloud.ai/faqs/) |
| HostKey (official) | [Dedicated GPU servers](https://hostkey.com/gpu-dedicated-servers/dedicated/), [support SLA](https://hostkey.com/services/sla-technical-support/) |
| E2E Networks (official) | [Pricing](https://www.e2enetworks.com/pricing), [GPU cloud](https://www.e2enetworks.com/gpu-cloud), [compute VMs](https://www.e2enetworks.com/cloud-compute-vms) |
| Google Cloud | [Server price (third party)](https://gcloud-compute.com/g2-standard-8.html), [Enhanced support (official)](https://cloud.google.com/support/enhanced), [disk price (third party)](https://gcloud-compute.com/diskpricing.html) |
| AWS | [Server price (third party)](https://trucost.cloud/instances/ec2/ap-south-1/g6.2xlarge), [support price](https://aws.amazon.com/premiumsupport/pricing), [support terms](https://aws.amazon.com/premiumsupport/plans/business-plus), [SLA](https://aws.amazon.com/compute/sla/), [disk price](https://aws.amazon.com/ebs/pricing) |
| Exchange rates | [USD/INR](https://tradingeconomics.com/india/currency), [currencies](https://www.morningstar.com/markets/currencies) |

The Google support and SLA pages did not load their text when checked; the response time shown for Google comes from a search result of the
official support page.
