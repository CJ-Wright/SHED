---
title: 'SHED: Streaming Heterogeneous Event Data'
tags:
  - Python
  - x-ray science
  - synchrotron
authors:
  - name: Christopher J. "CJ" Wright
    orcid: 0000-0003-0872-7098
    affiliation: 1
  - name: Simon J.L. Billinge
    orcid: 0000-0000-0000-0000
    affiliation: "1, 2"
affiliations:
 - name: Department of Applied Physics and Applied Mathematics, Columbia University New York NY 10027
   index: 1
 - name: Institution 2
   index: 2
date: 1 May 2019
bibliography: paper.bib
---

# Summary

## Bluesky and the event model
1. Bluesky by DAMA provides a way to perform scientific experiments with the
results streamed live in the event model.
1. For streaming libraries like rapidz/streamz to work we need to translate 
from the event model to the data's literal form.
1. SHED provides this translation layer, allowing for the building of flexible 
data analysis pipelines which perform live data processing for experiments
using the bluesky system.
1. The SHED system performs translation back to the event model enabling
using the 

## Data provenance
1. In addition to translating between literals and the event model, SHED 
tracks the provenance of the analyzed data by capturing the incoming data's 
unique identifiers, the graph which represents the data processing and the
order of the data's insertion.


# Citations

Citations to entries in paper.bib should be in
[rMarkdown](http://rmarkdown.rstudio.com/authoring_bibliographies_and_citations.html)
format.

# Acknowledgements

We acknowledge contributions from Brigitta Sipocz, Syrtis Major, and Semyeong
Oh, and support from Kathryn Johnston during the genesis of this project.

# References