# Sample Findings Output

A concrete, valid example of findings output conforming to the findings schema. Use this as a reference when authoring or debugging agent prompts.

---

## Example: Domain Lead Report — Technical Engineering

This example shows a Domain Lead that handled one sub-topic directly and delegated two to Specialists.

```json
{
  "domain": "Technical Engineering",
  "mandate": "Investigate friction stir welding (FSW) applicability to Al-Li aerospace structures",
  "depth_level": 1,
  "self_researched": true,
  "completeness": 0.85,
  "issues": [
    "One key NASA technical report was paywalled — could not verify specific tensile strength data for 2099-T83 alloy variant"
  ],

  "complexity_assessment": {
    "overall_score": 0.65,
    "signals": {
      "topical_breadth": 0.8,
      "authoritative_disagreement": 0.5,
      "source_type_diversity": 0.4,
      "query_residual": 0.7,
      "temporal_spread": 0.3
    },
    "decision": "selective_decompose",
    "sub_topics_delegated": 2,
    "sub_topics_handled_directly": 2
  },

  "key_findings": [
    {
      "claim": "FSW produces joints in 2xxx and 7xxx series Al-Li alloys with 80–95% of parent material tensile strength, significantly outperforming conventional fusion welding (50–70% joint efficiency) due to elimination of hot cracking and reduced heat-affected zone degradation.",
      "confidence": "High",
      "self_researched": false,
      "evidence": [
        {
          "source_url": "https://doi.org/10.1016/j.msea.2023.144871",
          "source_title": "Joint efficiency and microstructural evolution in FSW of 2198-T8 Al-Li alloy",
          "source_quality": 0.88,
          "source_read_success": true,
          "relevant_excerpt": "Peak tensile strength of FSW joints reached 486 MPa (91.4% joint efficiency) at optimized rotational speed of 1200 rpm and traverse speed of 200 mm/min, with fracture occurring in the thermomechanically affected zone rather than the nugget."
        },
        {
          "source_url": "https://ntrs.nasa.gov/citations/20210017342",
          "source_title": "NASA Technical Report: Friction Stir Welding of Aluminum-Lithium Alloys for Space Launch Vehicle Applications",
          "source_quality": 0.92,
          "source_read_success": true,
          "relevant_excerpt": "Production FSW panels fabricated for the Space Launch System (SLS) barrel sections from 2195-T8P achieved consistent joint efficiencies of 87–93%, with fatigue life exceeding fusion-welded equivalents by a factor of 2.4x in high-cycle regimes."
        }
      ],
      "contradicting_evidence": [
        {
          "source_url": "https://doi.org/10.1016/j.msea.2022.143102",
          "source_title": "FSW joint efficiency limitations in 8090-T651 Al-Li alloy with elevated Li content",
          "source_quality": 0.72,
          "source_read_success": true,
          "relevant_excerpt": "Joint efficiency for 8090-T651 (Li content 2.4 wt%) plateaued at 74% regardless of parameter optimization, attributed to preferential precipitation of delta-prime phase at grain boundaries during thermal cycling.",
          "why_overridden": "The 8090 alloy used in this study has a significantly higher Li content (2.4 wt%) than the 2xxx-series Al-Li alloys (1.0–1.8 wt%) used in current aerospace production. The lower joint efficiency is alloy-composition-specific, not a general FSW limitation. The NASA SLS production data and Elsevier 2198 study both use alloys consistent with current aerospace qualification practice."
        }
      ],
      "implications": "FSW is not merely an alternative to fusion welding for Al-Li structures — it is technically superior for structural integrity. The 80–95% joint efficiency range is sufficient for primary structure applications, which typically require ≥80% efficiency per FAA/EASA structural substantiation standards."
    }
  ],

  "evidence_digest": [
    {
      "claim": "FSW joint efficiency in 2195-T8P Al-Li alloy reaches 87–93% in production SLS barrel sections",
      "source": "https://ntrs.nasa.gov/citations/20210017342",
      "confidence": "High",
      "specialist_depth": 1
    },
    {
      "claim": "FAA AC 25.571-1E requires static strength and fatigue/damage tolerance substantiation for primary structure joints; no blanket approval exists for FSW — each application requires dedicated DT test program",
      "source": "https://doi.org/10.1016/j.ast.2023.108621",
      "confidence": "Moderate",
      "specialist_depth": 2
    }
  ],

  "specialist_reports": [
    {
      "domain": "Al-Li Metallurgy under FSW",
      "mandate": "Characterize the microstructural evolution and mechanical property changes in Al-Li alloys subjected to FSW thermal cycles, with emphasis on precipitate behavior and grain refinement",
      "depth_level": 2,
      "self_researched": true,
      "completeness": 0.78,
      "issues": [
        "Limited peer-reviewed data on 2099 alloy FSW behavior post-2020 — most studies predate recent alloy reformulations"
      ],

      "complexity_assessment": {
        "overall_score": 0.45,
        "signals": {
          "topical_breadth": 0.5,
          "authoritative_disagreement": 0.4,
          "source_type_diversity": 0.3,
          "query_residual": 0.6,
          "temporal_spread": 0.4
        },
        "decision": "no_decomposition",
        "sub_topics_delegated": 0,
        "sub_topics_handled_directly": 3
      },

      "key_findings": [
        {
          "claim": "FSW thermal cycles (peak temperatures 350–480°C in the nugget zone) cause partial dissolution of strengthening T1 (Al2CuLi) precipitates, followed by reprecipitation of finer T1 and delta-prime (Al3Li) phases during post-weld natural aging, which partially restores strength but alters fatigue crack path morphology.",
          "confidence": "Moderate",
          "self_researched": true,
          "evidence": [
            {
              "source_url": "https://doi.org/10.1016/j.actamat.2022.118247",
              "source_title": "Precipitate evolution and hardness recovery in FSW of 2198-T851 Al-Li alloy",
              "source_quality": 0.91,
              "source_read_success": true,
              "relevant_excerpt": "TEM analysis of the nugget zone revealed complete dissolution of T1 precipitates during FSW, with heterogeneous reprecipitation of T1 and delta-prime on subgrain boundaries during 96-hour natural aging. Vickers hardness recovered to 82% of base metal values without artificial aging."
            },
            {
              "source_url": "https://doi.org/10.1016/j.msea.2021.141628",
              "source_title": "Grain refinement and texture evolution in FSW Al-Li alloys: EBSD characterization",
              "source_quality": 0.85,
              "source_read_success": true,
              "relevant_excerpt": "Dynamic recrystallization in the nugget zone produces equiaxed grains of 2–8 μm, replacing the elongated deformation structure of the wrought alloy. The B/B-bar fiber texture component dominates, consistent with simple shear deformation."
            }
          ],
          "contradicting_evidence": [],
          "implications": "Post-weld aging treatment selection is critical for Al-Li FSW joints. Natural aging partially restores strength but artificial aging (T8 temper) after welding may induce distortion in large panel assemblies. This is a design constraint, not a disqualifying deficiency."
        }
      ],

      "evidence_digest": [],
      "specialist_reports": [],

      "synthesis": {
        "conclusion": "Al-Li alloys are metallurgically compatible with FSW provided that post-weld thermal management and aging protocols are specified in the design allowables. The nugget zone microstructure (fine equiaxed grains, partially dissolved T1 precipitates) is predictable and well-characterized for 2198 and 2195 alloys. Gaps remain for newer 2099 and 2060 formulations.",
        "confidence": "Moderate",
        "key_points": [
          "T1 precipitate dissolution is complete in the nugget zone but recovery via natural aging reaches ~82% of base metal hardness",
          "Grain refinement to 2–8 μm in the nugget zone provides fatigue crack initiation resistance",
          "Post-weld artificial aging improves strength recovery but must be balanced against distortion risk in large panels",
          "Alloy-specific data gaps exist for 2099 and 2060 Al-Li variants"
        ],
        "reasoning": "Multiple EBSD and TEM characterization studies with consistent methodology converge on the same precipitate evolution model. Confidence is capped at Moderate because (1) this is a Specialist report produced by sonnet, and (2) the data gap on 2099 represents a meaningful unknown for newer airframe programs."
      },

      "summary": "FSW of Al-Li alloys induces complete T1 precipitate dissolution in the nugget zone, followed by partial recovery through natural aging (82% hardness) or full artificial aging. Dynamic recrystallization produces fine equiaxed grains (2–8 μm) with B/B-bar shear texture. These microstructural changes are well-characterized for 2198 and 2195 alloys and are predictable enough to support design allowables development. Coverage is 78% complete — primary gap is limited post-2020 data on 2099 alloy FSW behavior under the alloy's most recent compositional specification.",

      "gaps_remaining": [
        "Microstructural characterization of FSW joints in 2099-T83 Al-Li alloy using the post-2019 compositional revision — existing studies predate the reformulation",
        "Long-term corrosion behavior of FSW nugget zone in 2198 alloy under combined mechanical loading and corrosive environment (corrosion-fatigue interaction)"
      ],

      "cross_domain_hooks": []
    }
  ],

  "synthesis": {
    "conclusion": "FSW is technically viable and demonstrably superior to fusion welding for Al-Li aerospace primary structure. Joint efficiencies of 87–93% in production SLS hardware establish a credible performance floor. The metallurgical behavior is well-understood for 2195 and 2198 alloys. The primary barrier to broader adoption is not technical performance but FAA certification pathway complexity and FSW tooling infrastructure cost.",
    "confidence": "High",
    "key_points": [
      "Joint efficiency of 80–95% for 2xxx Al-Li alloys, vs. 50–70% for fusion welding — structurally meaningful advantage",
      "NASA SLS production data provides flight-heritage credibility that laboratory studies alone cannot",
      "T1 precipitate dissolution is predictable and manageable with post-weld aging protocols",
      "FAA certification requires application-specific damage tolerance test programs — no blanket approval path exists",
      "FSW tooling infrastructure (pin tool wear, fixturing for large panels) represents a supply chain constraint independent of technical performance"
    ],
    "reasoning": "The Specialist's Moderate finding on metallurgy was elevated to High at the Domain Lead level by addition of independent NASA production evidence (NTRS 20210017342) demonstrating that the theoretical metallurgical performance is achieved in flight-qualified production hardware. The contradicting 8090 alloy study was evaluated and overridden on the basis of compositional non-representativeness."
  },

  "summary": "Friction stir welding is technically superior to fusion welding for Al-Li aerospace structures, achieving 87–93% joint efficiency in production SLS hardware (vs. 50–70% for fusion). The metallurgical basis is well-characterized: T1 precipitate dissolution is complete in the nugget zone but recovers to ~82% hardness via natural aging, and dynamic recrystallization produces fine equiaxed grains favorable for fatigue resistance. Coverage is 85% complete — one paywalled NASA report on 2099-T83 could not be verified, and the FAA certification pathway for new applications remains a significant program risk requiring dedicated damage tolerance substantiation.",

  "gaps_remaining": [
    "Tensile strength data for 2099-T83 Al-Li alloy under FSW could not be verified — key NASA technical report was paywalled (NTRS 20230012847); this data is needed to assess the newest-generation alloy used in some current commercial airframe programs",
    "FSW tooling wear rates and replacement cost data for Al-Li alloys at production volumes — required for manufacturing cost modeling and make/buy decisions"
  ],

  "cross_domain_hooks": [
    {
      "hook_id": "te-reg-faa-cert-001",
      "topic": "FAA certification pathway for FSW primary structure joints",
      "direction": "extends",
      "target_domains": ["Regulatory Compliance"],
      "description": "FAA AC 25.571-1E requires application-specific static strength and fatigue/damage tolerance substantiation for FSW joints in primary structure. No generic FSW approval exists. The Regulatory domain should investigate whether any Special Conditions or ELOS findings have been issued for FSW Al-Li primary structure on transport category aircraft, and what the current FAA DER guidance is for FSW joint DT test matrix scoping."
    },
    {
      "hook_id": "te-mfg-fsw-tooling-001",
      "topic": "FSW pin tool wear and fixturing infrastructure for Al-Li production",
      "direction": "extends",
      "target_domains": ["Manufacturing", "Supply Chain"],
      "description": "Al-Li alloys (particularly 2099 and high-Li variants) exhibit accelerated pin tool wear compared to 2024 and 7075. The Manufacturing and Supply Chain domains should investigate the current supplier landscape for FSW capital equipment, pin tool material options (W-Re alloys, PCBN), and the fixture investment required for large panel assembly — these are the primary cost and schedule drivers for FSW adoption decisions, independent of technical performance."
    }
  ]
}
```

---

## Notes

**Why the Lead's confidence is High when the Specialist's was Moderate.** The Specialist (a sonnet agent) produced a Moderate finding on T1 precipitate behavior — correctly capped at the sonnet confidence ceiling. The Domain Lead (an opus agent) independently retrieved the NASA SLS production report (NTRS 20210017342), which provides flight-qualified production evidence that the metallurgical performance is achieved in practice, not just in laboratory conditions. This independent evidence addition is what licenses the elevation from Moderate to High. Without the new evidence entry in the `evidence[]` array, the elevation would be a protocol violation.

**Specialist confidence ceiling.** Specialist agents running on sonnet have a hard ceiling of Moderate confidence. This is a deliberate architectural constraint, not a capability judgment — it creates a two-tier audit trail. If a claim needs to reach High confidence, it must pass through a Domain Lead (opus) that adds independent verification. The Specialist's Moderate rating in the `Al-Li Metallurgy under FSW` report is therefore correct even though the underlying evidence is high-quality peer-reviewed work.

**cross_domain_hooks flag topics for the Cross-Domain Analyst.** The two hooks in this example (`te-reg-faa-cert-001` and `te-mfg-fsw-tooling-001`) are not conclusions — they are signals. The Cross-Domain Analyst reads all domain summaries and `cross_domain_hooks[]` first to identify promising connections, then examines the relevant full report sections. Hooks are how the Technical Engineering domain says "the Regulatory and Manufacturing domains need to know about this."

**evidence_digest provides a flat list for initial scan.** The `evidence_digest[]` at the top level contains compact (claim, source, confidence, specialist_depth) tuples from across all nested Specialists. This allows the Cross-Domain Analyst and Research Director to scan raw evidence without parsing the full recursive `specialist_reports[]` tree. The digest is additive — the full evidence is always available in the nested reports.

**specialist_reports is recursive and uses the same schema.** The `specialist_reports[]` array contains full findings objects conforming to the same schema as the parent. A Specialist at depth 2 that itself spawned sub-Specialists would have its own `specialist_reports[]`. The schema is self-similar by design. In practice, default `--max-depth 2` means Specialists are typically leaf nodes with empty `specialist_reports[]`.
