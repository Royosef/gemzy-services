"""Exact v5.2 pure jewelry prompt mappings synced from the HTML generator."""

from __future__ import annotations

from typing import Iterable

from .models import GenerationItem

V52_PROMPT_VERSION = "v5.2"
_DEFAULT_COLOR_HEX = "#C9A84C"

_HERO = """Ultra-realistic jewelry product photograph. The standard is the finest luxury jewelry brand campaigns — Cartier, Tiffany, Van Cleef & Arpels, Bulgari. Every detail of the jewelry is rendered with complete material truth: accurate metal reflectivity, honest gemstone behavior, sharp edges, precise craftsmanship detail.

The only jewelry in the image is what was uploaded — maximum 4 pieces. Nothing added, nothing invented, nothing assumed. This rule is absolute.

The image feels photographed, not generated. The jewelry feels real enough to pick up."""

_QUALITY = """QUALITY CONTROL — ALL RULES ARE ABSOLUTE:

JEWELRY: 1) Always fully visible and unobstructed. 2) Complete material accuracy — realistic reflectivity, accurate gemstones, sharp edges, fine detail. No sparkle effects, no lens flare. 3) Edges always sharp and readable. 4) Only the uploaded jewelry appears — nothing added, invented, or assumed. This cannot be overridden.

MATERIAL BEHAVIOR: 5) Chains drape and pool naturally following gravity — and surface contours where a surface is present. Never in a perfect circle. Never in an impossibly neat arrangement. 6) Rings rest at natural angles — never perfectly upright unless the surface demands it. 7) The interior of rings and bangles is visible from at least one angle where the composition allows. In top-down flat lay compositions this rule is suspended — the face of the piece is the subject. 8) Earring pairs show natural variation in angle and position — never perfect mirror symmetry.

TECHNICAL: 9) No AI artifacts — no texture bleeding, geometry distortion, or repeating elements. 10) Background coherent and continuous. 11) Surface materials render with complete physical accuracy — fabric texture, stone grain, water refraction all behave correctly. 12) Lighting is physically coherent — shadows fall in the correct direction, reflections appear on correct surfaces.

FINAL: 13) Would the jewelry director of Cartier, Tiffany, or Van Cleef & Arpels approve this image for their campaign? If not — it is not finished."""

_DISPLAY_FORM_ADAPTATION = """When the selected jewelry is designed for the neck or collarbone — a necklace, pendant, or choker — the form presents it exactly as intended, the piece draping naturally at the appropriate height.

When the selected jewelry is designed for another part of the body — a ring, bracelet, watch, earrings, brooch, or any piece not worn at the neck — the form adapts. It provides a surface, ledge, or natural resting point where the jewelry sits with clarity and intention. The jewelry is never forced onto a neck position where it does not belong. It finds the most natural and beautiful position the specific piece demands. The display form exists to elevate whatever jewelry it receives."""

_TYPE_ALIASES = {
    "Earring": "Earrings",
    "Hair Clip": "Hair Clips",
    "Hair Clips": "Hair Clips",
    "Headpiece": "Headpiece",
    "Headpieces": "Headpiece",
    "Cufflink": "Cufflinks",
    "Cufflinks": "Cufflinks",
}

_TYPE_PROMPTS = {
    "Earrings": """The jewelry is a pair of earrings. Both pieces are present in the frame unless the composition deliberately features one as hero. The earrings interact with their surface naturally — posts or hooks rest against or into the surface, drops or dangles follow gravity and settle at their natural hanging point. The two pieces are never arranged in identical mirror symmetry — one may be slightly offset, angled differently, or catching light from a different facet. Real objects placed by a human hand are never perfectly symmetrical.""",
    "Necklace": """The jewelry is a necklace with a chain and pendant or continuous chain design. The chain does not form a perfect circle or lie in an impossibly neat arrangement. Where a surface is present, the chain follows its contours — draping into folds of fabric, tracing the edge of a stone, pooling naturally where gravity pulls it. Where no surface is present, the chain hangs freely from its highest point, following only gravity — each end falling to its natural position with the pendant at the lowest point. Individual links catch light differently along the length. The pendant settles at the lowest natural point. The chain may overlap itself, cross over, or trail beyond the frame. The arrangement looks placed, not constructed.""",
    "Pendant": """The jewelry is a pendant on a chain. The pendant is the visual hero — the chain exists to lead the eye toward it. The chain drapes naturally from wherever it enters the frame, following gravity and surface texture with organic behavior. The pendant itself rests flat or at a slight angle determined by the surface beneath. The connection point between chain and pendant catches light as a distinct detail. The pendant's face is the focal point of the entire composition.""",
    "Choker": """The jewelry is a choker — a short, close-fitting necklace designed to sit at the throat. Without a neck to wear it, the choker rests on its surface as a compressed, slightly oval form — never a perfect circle. If on fabric, it settles into the weave. If on a hard surface, it may stand slightly on one edge or rest flat with natural contact points. The clasp or closure detail is visible and readable. The piece reads as something designed to be worn close — intimate in scale, precise in form.""",
    "Ring": """The jewelry is a ring. The ring does not stand perfectly upright unless deliberately balanced — it rests on its band at a natural angle, slightly tilted, the setting catching directional light from one side. On fabric it may sink slightly into the weave at its contact points. On stone or hard surfaces it casts a precise shadow from its form. The interior of the band is visible from at least one angle — a detail that makes it read as a wearable object, not a flat graphic. Multiple rings may lean against each other or be arranged at different angles.""",
    "Bracelet": """The jewelry is a bracelet. Chain bracelets drape and pool with the same natural behavior as necklace chains — links catching light individually, the form following surface contours rather than holding a perfect circle. Bangles and cuffs rest on their surface at a natural tilt — never perfectly upright unless the surface demands it, the interior curve catching shadow. Cuffs show the gap in their form as a design detail. The piece reads as something sized for a human wrist — scale matters.""",
    "Watch": """The jewelry is a watch — a timepiece with a case, dial, and bracelet or strap. The watch rests on its bracelet or strap with the dial face visible and readable. The dial is the compositional hero — it faces the camera with enough angle to read its detail. The crown, pushers, and case edge are visible as distinct details. The bracelet or strap follows its natural curve, settling into the surface with organic contact. The watch reads as a precision object — every detail of the case and dial rendered with complete accuracy.""",
    "Glasses": """The jewelry is a pair of eyewear — frames with lenses. The glasses rest on a surface the way they would if set down by a human hand — on their front face with the temples folded, or open with the temples extended and the frame tilted at a natural angle. The lenses catch the light of the scene — reflecting the environment subtly without completely obscuring the frame beneath. The frame material and construction details are all readable. The piece has the particular quality of something that belongs to someone.""",
    "Brooch": """The jewelry is a brooch. On fabric surfaces the brooch sits as if pinned — the piece sitting flush with a slight impression in the fabric around it. On hard surfaces it rests on its pin back at a natural tilt, the decorative face angled toward the camera. The brooch demands to be seen from the front — its design made for exactly this angle. Its stones and construction are fully visible and readable.""",
    "Hair Clips": """The jewelry is a hair clip or clips. The clip or clips rest on their surface with the mechanical jaw or hinge visible as a design detail. Multiple clips may be arranged in a loose cluster or scattered with intentional organic randomness — never in perfect grid alignment. The opening mechanism of the clip catches light along its edge. Function and decoration are inseparable here — the hardware is as beautiful as the jewel.""",
    "Headpiece": """The jewelry is a headpiece. Removed from the body, the headpiece rests on its surface as a pure architectural object — its full span visible, the center detail forward-facing. On fabric it drapes with the natural weight of its structure. On a hard surface it balances on its contact points, the chain or band following its natural curve. The piece is presented at its full width — never folded or compressed. It reads as something grand even at rest.""",
    "Tiara": """The jewelry is a tiara. The tiara rests on its surface as a complete architectural form — its full arc visible, the center as the compositional peak. The tiara is never tilted so far that its form reads as flat — the three-dimensionality of the arc is always present. Gemstones and metalwork catch light from multiple points simultaneously. Everything about it communicates preciousness — even at rest, even alone.""",
    "Cufflinks": """The jewelry is a pair of cufflinks. Both pieces are present in the frame. They rest on their surface face-up, the decorative face toward the camera, at slightly different angles — never perfectly parallel. Their small scale demands that the composition brings the camera close enough to read their detail. The pair has a relationship — close but not touching, separate but belonging together.""",
    "Anklet": """The jewelry is an anklet. The anklet behaves exactly as a necklace chain on a surface — draping, following contours, pooling naturally at gravity's pull. Its scale is delicate — the chain is fine and the overall form is small relative to the frame. The composition brings the camera close enough that the delicacy of the chain reads clearly — individual links visible, the clasp detail readable.""",
    "Body Chain": """The jewelry is a body chain. Removed from the body, the body chain is arranged on its surface with its full design visible — the main chains laid out to suggest their intended path, the connecting pieces and pendants settled at natural points. Its full scale and the complexity of its design demand space in the frame. The arrangement is deliberate but never mechanical — it looks like something laid out by someone who understood its form.""",
}

_SIZE_PROMPTS = {
    "Very Small": """The piece is very small and delicate — minimal in scale. Framing and light are always close enough to make the piece clearly readable. The piece is never lost against the surface.""",
    "Small": """The piece is small and refined — understated in scale. Light falls with enough precision to reveal its form and detail.""",
    "Medium": """The piece is moderate in scale — present and noticeable without dominating the frame.""",
    "Big": """The piece is large and bold — commanding attention. The framing is always wide enough to contain it completely.""",
    "Very Big": """The piece is very large — a dominant sculptural presence. The composition is built around its scale.""",
}

_SHARED_LIGHTING = {
    "Soft Diffused": """Light wraps the jewelry from multiple directions simultaneously — a large diffused source that eliminates harsh shadow pockets and reveals the jewelry's form in its entirety. Every surface of the piece is visible and readable. Shadows are soft and gradual. The light reveals rather than sculpts — the jewelry is fully present without drama.""",
    "Hard Directional": """A single strong light source from a defined angle — undiffused, producing crisp shadow edges that cut across the surface with graphic precision. The lit side of the jewelry carries bright clean highlights. The shadow side falls into genuine darkness. The contact shadow on its surface is sharp and deliberate. Light and shadow do equal work.""",
    "Side Rim": """A narrow light source positioned at the side or rear of the jewelry, creating a bright rim of light along one or both edges of the piece. The rim separates the jewelry from its background with a precise line of light — the edges of the metal glow while the face remains in relative shadow. The technique reveals the three-dimensional form and silhouette with maximum precision.""",
    "Top Down": """Light falls from directly above the jewelry — a clean vertical source that illuminates the top surfaces while allowing the sides to fall into natural shadow. The contact shadow falls directly beneath the jewelry, compressed and centered. Top down light reveals the flat face of the jewelry with complete clarity — gemstones face the light directly, settings are fully visible.""",
    "Backlit": """The primary light source is positioned behind the jewelry. Light wraps around the edges, creating a luminous rim along its perimeter. Transparent or translucent elements — gemstones, colored glass, enamel — are illuminated from within by the backlight, glowing with transmitted color. Ethereal, precious, and alive.""",
    "Bloom": """The light is positioned to create a natural optical bloom effect on the jewelry's metal surfaces — a soft, luminous spread of light emanating from the brightest specular highlight points as it would in a real long-exposure or wide-aperture photograph. This is not an artificial sparkle effect, not a starburst, not a graphic overlay. It is the natural behavior of real light hitting real polished metal — the highlight exceeds the sensor's capture range and spreads softly into the surrounding area. The bloom is subtle and controlled — it enhances the jewelry's luminosity without obscuring its form or detail.""",
}

_COMPOSITION = {
    "Centered": """The jewelry is positioned at the absolute center of the frame — perfectly balanced, symmetrically placed, compositional weight distributed evenly in all directions. The background is equal on all sides. The jewelry commands the frame by occupying its exact center. Shot on a Canon EOS R5, 85mm, f/4.0, ISO 100. The camera sits at the jewelry's own level — not above, not below. Classic, authoritative, and timeless.""",
    "Off Center": """The jewelry is positioned deliberately in one third of the composition — generous negative space occupies the opposing side. The negative space is active and breathing, giving the jewelry room to exist without compression. Shot on a Canon EOS R5, 85mm, f/4.0, ISO 100. Camera at the jewelry's level. Editorial and contemporary — the visual language of a brand that doesn't need to fill every inch of the frame to be confident.""",
    "Close Up": """The camera moves in close — the jewelry fills the majority of the frame, individual details readable at a scale the human eye cannot achieve in real life. Setting prongs, metal grain, gemstone facets, chain links — all individually visible and precise. Shot on a Canon EOS R5, 100mm macro, f/4.5, ISO 100. Depth of field is shallow — the jewelry in razor-sharp focus, the surface beneath and background beyond fall into soft abstraction. The world reduced to the jewelry.""",
    "Flat Lay": """The camera is positioned directly above the jewelry, looking straight down — a pure top-down compositional view. No horizon, no background depth — only the surface and the jewelry on it. The arrangement reads as pattern, form, and object simultaneously. Shot on a Canon EOS R5, 50mm, f/5.6, ISO 100. The deeper depth of field ensures both the near and far edges of the composition remain in sharp focus. Every detail of the jewelry and the surface beneath it readable.""",
    "Angled": """The camera approaches the jewelry from a low angle — positioned close to the surface level, looking across rather than down at the piece. The jewelry rises from its surface with dimensional presence, the background visible and soft beyond it. Shot on a Canon EOS R5, 85mm, f/3.2, ISO 100. The lower aperture creates beautiful separation between the jewelry in sharp focus and the surface stretching behind it toward a softly blurred background. The most architectural of all compositions.""",
    "Depth Play": """Two or more pieces are arranged at genuinely different distances from the camera — creating real spatial separation the eye travels across. The piece closest to the camera is large in the frame and fully detailed. The piece further from the camera is smaller and slightly softer in focus — present and readable, never reduced to an unrecognizable blur. Both pieces remain identifiable as the same jewelry. Shot on a Canon EOS R5, 100mm macro, f/2.8, ISO 100. The wide aperture creates meaningful depth of field separation between the near and far pieces — enough to feel spatial and dimensional, not enough to lose the detail of the further piece entirely.""",
    "Touching": """Two or more pieces are in deliberate light physical contact with each other — leaning against one another, one resting on the edge of another, overlapping at a single defined point. The contact is gentle and specific — never a merger. Both pieces remain completely distinct objects. The exact place where one object ends and the other begins is always clear. Shot on a Canon EOS R5, 100mm macro, f/4.5, ISO 100. The close focal length keeps both pieces sharp at their contact point while the surface and background fall away softly.""",
    "Scattered": """Two or more pieces are arranged with deliberate organic distance — no two pieces at the same angle, no two pieces equidistant from each other or from the frame edges. The arrangement looks like it happened rather than was constructed. Each piece is fully visible and fully readable — the scatter never places one piece behind another. Shot on a Canon EOS R5, 50mm, f/5.6, ISO 100. The wider lens and deeper depth of field ensure every piece across the scattered arrangement is in sharp focus simultaneously.""",
    "Wide Environmental": """The camera pulls back far enough to show the jewelry as an object within its full environment — the surface it rests on, the space around it, the background behind it all visible and contributing to the composition. The jewelry is not the entire frame — it is a considered element within a larger visual world. Shot on a Canon EOS R5, 35mm, f/8.0, ISO 100. The wider lens and deep depth of field keep both the jewelry and its full environment in sharp focus simultaneously — every element of the scene from the surface beneath the jewelry to the background behind it readable with clarity.""",
}

_PURE_JEWELRY_STYLES = {
    "pure-studio": {
        "atmosphere": """A controlled environment where nothing competes with the jewelry. Every surface, every light source, every shadow exists in service of the piece. Distraction is eliminated. What remains is the jewelry — fully present, fully itself, nothing between it and the viewer.""",
        "categories": [
            ("scene", "SCENE", {
                "Studio Color": {"prompt": """A controlled studio built entirely around [HEX]. That color saturates the background completely — rich, deep, intentional. Soft directional key light sculpts the jewelry while [HEX] holds at full depth behind it. The jewelry reads clearly against the color field — contrast between metal and [HEX] is always preserved. No gradients, no texture. Pure color as environment.""", "has_color": True},
                "Pure White": """A pure white seamless studio environment. No background detail, no shadow on the backdrop, no environmental context. Light is bright, even, and controlled — wrapping the jewelry from multiple directions to eliminate harsh shadow while maintaining material dimension. Clinical, precise, editorial.""",
                "Soft Gray": """A neutral mid-gray seamless studio environment. Neither warm nor cool — a perfectly balanced neutral. Light is soft and controlled, wrapping evenly from a defined direction. The gray creates gentle separation between the jewelry and the background without drama or distraction.""",
                "Deep Black": """A near-black studio environment that absorbs light completely. No background detail, no horizon line. A controlled light source sculpts the jewelry from one direction, pulling it out of the darkness with precision. Metal surfaces emerge with intensity against the deep background. The jewelry feels precious and rare — lit like something kept in a vault.""",
                "Warm Ivory": """A warm ivory seamless studio environment — the soft warmth of natural cream. Light is gentle and directional, carrying warmth into the highlights on the jewelry surface. Gold jewelry glows with particular richness against this tone. Silver reads with refined contrast.""",
                "Soft Gradient": """A seamless studio background that transitions gradually from a lighter tone to a deeper one — the AI determines the most flattering gradient direction for the jewelry present. The gradient is subtle and controlled — never dramatic, never calling attention to itself. It exists only to give the jewelry a background with quiet depth.""",
            }),
            ("surface", "SURFACE", {
                "Studio Seamless": """The jewelry rests on a surface that is indistinguishable from the background behind it — the same tone, the same material, the same light. No visible horizon line separates the floor from the backdrop. No texture, no edge, no transition point. The jewelry behaves naturally — chains pool and drape with gravity, rings rest at their natural angle, pieces settle with genuine weight. A soft, subtle contact shadow directly beneath the jewelry is the only evidence that a surface exists. The jewelry simply appears — emerging from a seamless field of light and color, grounded but unanchored, present but floating.""",
                "Floating": """The jewelry exists in pure space — suspended in air with no surface beneath, beside, or behind it that the jewelry touches or interacts with. Gravity is fully active on the jewelry itself — chains hang and drape downward from their suspension points, pendants fall to their lowest natural position, links separate with the weight of real metal in real air. No contact shadow falls on any surface. No ground plane is implied. No surface reflection exists unless the jewelry's own optical presence creates a very faint ghost of itself directly beneath — never a cast shadow, only the faintest material echo. The background is pure and uninterrupted in every direction. The piece exists entirely alone — isolated in space, defined only by light and gravity.""",
                "Silk": """The jewelry rests on silk fabric — smooth, lustrous, and fluid. The fabric surface catches light along its natural folds and drapes. The jewelry settles into the silk with natural weight — the fabric responds to its presence, the contact points visible as subtle impressions. The sheen of silk and the sheen of metal exist in conversation.""",
                "Linen": """The jewelry rests on linen fabric — matte, textured, and naturally imperfect. The visible weave creates a tactile contrast against the precision of the jewelry. The jewelry settles into the linen with genuine weight — the weave visible at the contact points.""",
                "Velvet": """The jewelry rests on velvet — deep, light-absorbing, and rich. The velvet surface creates dramatic contrast against the reflective surfaces of the jewelry — where the velvet absorbs, the metal reflects. The pile of the velvet shows directional light across its surface.""",
                "Marble": """The jewelry rests on a marble surface — smooth, cool, and veined with natural mineral patterns. The marble's veining creates an organic compositional element beneath the jewelry without competing with it. The polished marble surface may carry a subtle reflection of the jewelry above it.""",
                "Stone": """The jewelry rests on natural stone — rough, textured, and organically imperfect. The raw surface creates maximum contrast against the refined precision of the jewelry. The AI selects the most compelling stone type — sandstone, limestone, granite, slate. The jewelry rests in a natural pocket or on a flat face of the stone.""",
                "Ceramic": """The jewelry rests on or within a ceramic surface or vessel — smooth, matte, and precise. The ceramic may be a flat plate, a shallow dish, or a curved bowl — the AI selects the most natural relationship between the ceramic form and the jewelry type. The contrast between the handmade quality of ceramic and the precision of fine jewelry is quiet and deeply sophisticated.""",
                "Glass": """The jewelry rests on, within, or against a glass surface or vessel. Glass introduces transparency, refraction, and reflection simultaneously. Light passing through glass creates secondary light sources on the surface beneath. The relationship between glass and jewelry is one of shared optical complexity — both materials play with light in ways that amplify each other.""",
                "Wood": """The jewelry rests on a wooden surface — the grain, warmth, and natural imperfection creating an organic contrast against the precision of the metal. The AI selects the most flattering wood tone for the jewelry. Gold jewelry against dark wood creates warmth and richness. Silver against pale wood reads as cool and precise.""",
                "Water": """The jewelry rests in or on water — surrounded by the optical complexity of a liquid surface. Water creates light refraction patterns that move across the jewelry and the surrounding surface. The jewelry may rest on the floor of a shallow water surface, surrounded by refracted light patterns. The water is calm — no ripples that obscure, only the gentle optical dance of light through liquid.""",
            }),
            ("lighting", "LIGHTING", _SHARED_LIGHTING),
            ("shadow", "SHADOW", {
                "None": """No shadow is present in the image. The jewelry exists without a contact shadow, without a cast shadow, without any shadow on the background. The lighting is designed to eliminate shadow entirely — multiple sources wrapping the piece from all directions. Clean, clinical, ghost-free.""",
                "Soft": """A gentle, diffused shadow falls from the jewelry onto its surface — present but never dominant. The shadow edges are soft and gradual, the shadow itself light in tone. It exists to ground the jewelry in space — to confirm that the piece has weight and dimension — without calling attention to itself.""",
                "Hard": """A sharp, defined shadow falls from the jewelry onto its surface — edges crisp and precise, the shadow tone deep and committed. The shadow is a graphic element as deliberate as the jewelry itself. Its shape is an exact silhouette of the jewelry's form. The shadow tells you everything about the piece's structure that the lit face cannot.""",
                "Dramatic": """The shadow is a major compositional element — long, deep, and deliberate. The light source is low and directional, casting the shadow far across the surface. The shadow may be longer than the jewelry itself. It may cross the frame edge. The shadow is not a side effect — it is a co-subject. The jewelry and its shadow compose the image together.""",
            }),
            ("composition", "COMPOSITION", _COMPOSITION),
        ],
    },
    "object-world": {
        "atmosphere": """The jewelry has left the display case and entered the world. Whatever it has found here — whatever object it now shares space with — gives it a context it could never have in a studio. The pairing is unexpected. The result is unforgettable.""",
        "categories": [
            ("object-territory", "OBJECT TERRITORY", {
                "Table & Kitchen": """The object comes from the world of the table, the kitchen, the everyday ritual of eating and living — a piece of cutlery, a ceramic vessel, a glass, a plate, a bowl, a piece of food in its most beautiful and unexpected form, a cutting board, a carafe. The object is chosen for its visual relationship with the jewelry — its scale, its material, its surface quality. The object is rendered with the same material honesty as the jewelry.""",
                "Living & Fresh": """The image draws from the living, growing world freely — matter that is visibly alive, hydrated, and at its peak of color and vitality. A freshly cut flower with petals fully intact and vibrant, a green leaf with visible cell structure, fresh herbs, a living cactus pad, a piece of ripe fruit at its most colorful moment, a stem with a bud about to open. No dried flowers, no wilted petals, no dead or decaying matter. The botanical element is saturated with its own natural color — green, pink, red, white, yellow — creating a vivid living contrast against the precision of the jewelry.""",
                "Luxury Objects": """The object is drawn from this territory without restriction — things from the world of beautiful, considered objects that share the jewelry's register of quality and intention. A velvet jewelry pouch, a ribbon of silk or satin, a small precious box, a perfume bottle, a length of fine cord, a wax seal, a folded piece of fine paper, a small mirror, a beautiful container. The object exists in the same world as the jewelry, sharing its commitment to material quality. The pairing feels curated — intentional, the language of a brand that knows what it is.""",
                "Mineral & Geological": """This territory is explored freely — matter formed over millions of years by pressure, heat, and mineral process. A geode split open to reveal its crystal interior, an amethyst or quartz cluster, a raw uncut mineral specimen, a piece of polished agate with its layered banding, a chunk of obsidian, a fragment of pyrite, a piece of malachite, a calcite formation, a raw crystal point. The natural facets of minerals catch light in ways that amplify the jewelry's own gemstone behavior — two kinds of crystalline precision in the same frame, one formed by nature over millions of years, one crafted by human hands in hours.""",
                "Glass & Vessels": """The selection is made freely within this territory — glass or transparent vessels whose defining quality is their interaction with light. A wine glass, a crystal bowl, a glass carafe, a transparent vessel of any form, a glass bottle, an amber or colored glass object. Glass introduces optical complexity that no opaque surface can — refraction, reflection, transparency, the color cast of tinted glass. Both materials play with light, and together they produce something neither achieves alone.""",
                "Personal & Found": """The object is chosen freely from this intimate world — objects that carry the implication of a life being lived. An open book or letter, a key or set of keys, a matchbook, a coin, a small notebook, a postcard, a small personal object whose exact nature is ambiguous but whose intimacy is clear. The jewelry and the personal object together imply a story the viewer cannot fully read — which is exactly what makes the image impossible to ignore.""",
                "Open": """No territory is defined. The AI selects the object freely from anywhere in the world — guided only by what creates the most surprising, beautiful, and unexpected relationship with the specific jewelry present. The AI has complete creative authority over the object selection. The only constraints are: the object must be real, the pairing must be genuinely surprising, and the relationship between the jewelry and the object must feel inevitable in retrospect — the way all great creative decisions do.""",
            }),
            ("relationship", "RELATIONSHIP", {
                "Resting On": """The jewelry rests on the surface of the object — making full contact, following the object's contours with natural weight and gravity. The jewelry does not float above or hover near the object — it is genuinely in contact, and that contact is visible. The relationship is one of the jewelry having found its resting place — temporary, natural, as if placed by a hand a moment before the shutter opened.""",
                "Draped Over": """The jewelry follows the form of the object — draping over an edge, a curve, a peak, conforming to the object's three-dimensional shape with the natural compliance of chain, cord, or flexible metal. The chain or band of the jewelry becomes a line that traces the object's form — revealing its shape by following it. The relationship is one of the jewelry belonging to the object for this moment.""",
                "Inside": """The jewelry sits within the interior of the object — in a bowl, a dish, a glass, a box, a vessel that creates a contained space around the piece. The object holds the jewelry — partially or fully surrounding it. The relationship is one of the object protecting the jewelry — a vessel designed to contain something precious now containing exactly that.""",
                "Beside": """The jewelry and the object exist as equals in the frame — neither on nor in nor over the other, but beside, sharing space with mutual respect and distance. The gap between them is intentional — close enough to create a relationship, far enough to make each object completely independent. They are in conversation — telling each other something the viewer is allowed to overhear.""",
                "Threaded Through": """The jewelry passes through, around, or between elements of the object — a chain through the tines of a fork, a ring around a stem, a bracelet looped through a handle or opening, a necklace wound through the pages of a book. The threading is natural and physically plausible. The jewelry and the object are temporarily inseparable, neither one making complete sense without the other in this moment.""",
            }),
            ("lighting", "LIGHTING", _SHARED_LIGHTING),
            ("mood", "MOOD", {
                "Editorial": """The image has the intentional, art-directed quality of a magazine spread — every element in the frame feels chosen and placed with complete deliberateness. Nothing is accidental. The lighting is precise, the relationship between jewelry and object is intentional. The image could run in a fashion or luxury publication without a single element changed. It communicates a point of view.""",
                "Intimate": """The image has a private, close quality — as if the camera has been allowed into a personal space that is not usually photographed. The scale is small and human. The light is soft and near. The relationship between the jewelry and the object feels like something that happened rather than something that was arranged. The viewer feels like they are seeing something they were not quite supposed to see.""",
                "Playful": """The image has a light, unexpected quality — the combination of jewelry and object produces a genuine smile of recognition. The pairing is surprising enough to be funny and beautiful enough to be taken seriously. The overall feeling is of a brand secure enough in its luxury to not take itself too seriously. The jewelry is in on the joke — and the joke makes it more desirable, not less.""",
                "Cinematic": """The image has the atmospheric quality of a frame from a film — light that tells a story, a relationship between objects that implies a narrative, a mood that exists before and after the frame itself. Something has just happened or is about to happen in the world of this image — the viewer cannot tell which, and that ambiguity is the entire point.""",
            }),
            ("composition", "COMPOSITION", _COMPOSITION),
            ("brand-accent", "BRAND ACCENT", {
                "Brand Accent": {"prompt": """The color [HEX] is present somewhere in the image as a natural element — not as a background, not as an overlay, but as the genuine color of something that already exists in the scene. The AI finds the most natural and beautiful carrier for this color within the selected object territory and relationship — the color of a flower, the tint of a glass vessel, the hue of a fabric, the tone of a ceramic surface, the color of a ribbon or pouch. The color [HEX] appears as if it was always going to be there — discovered rather than applied. It is the brand's presence in the image — quiet, intentional, and entirely belonging.""", "has_color": True},
            }),
        ],
    },
    "surface-light": {
        "atmosphere": """The surface and the light arrived first. The jewelry was placed into them — and something happened that could not have been planned. The environment is not a backdrop. It is a collaborator. The jewelry belongs here completely.""",
        "categories": [
            ("surface", "SURFACE", {
                "Sand": """The jewelry rests on sand — fine, natural, and textured. The sand surface has natural variation: subtle ripples, slight depressions, the impression of the jewelry's own weight settling into it. Individual grains are visible at the edges of the jewelry where they meet the metal. The jewelry settles into the sand with genuine weight — slightly embedded, not floating above.""",
                "Stone Slab": """The jewelry rests on a natural stone slab — a flat, horizontal surface of real rock with visible mineral grain and natural variation in tone. The AI selects the most flattering stone type for the jewelry — limestone, slate, granite, or sandstone. The jewelry's contact with the stone is precise and clean — metal against mineral, two different kinds of earth-made material in the same frame.""",
                "Fabric Drape": """The jewelry rests on or within draped natural fabric — the surface not flat but folded, gathered, and dimensional. The fabric is a natural material — linen, cotton, silk, velvet, wool, or canvas. Its color complements rather than competes — a neutral or earth tone that lets the jewelry read with complete clarity against the textile landscape beneath it. The jewelry settles into the folds with genuine weight, the fabric responding to its presence at the contact points.""",
                "Water Surface": """The jewelry rests in shallow water — the surface above it alive with the optical behavior of light through liquid. Refraction patterns move across the jewelry and the surface beneath — caustic light patterns creating a living, shifting secondary light source. The water is perfectly clear and very shallow — the jewelry is fully visible beneath or through the surface, its detail uncompromised by depth.""",
                "Wood Grain": """The jewelry rests on a wooden surface — the grain visible, directional, and full of the particular warmth that only organic material shaped by years of growth can hold. The AI selects the most flattering wood tone — light and pale, or dark and rich. The grain lines create natural compositional structure beneath the jewelry, leading the eye or framing the piece within the surface.""",
                "Concrete": """The jewelry rests on concrete — raw, textured, and unapologetically industrial in its material honesty. The aggregate of the concrete is visible at the surface — small stones and mineral particles embedded in the grey matrix. The jewelry rests on this surface with precise contact — the roughness of the concrete creating maximum contrast against the refined precision of the metal. Urban, modern, and quietly powerful.""",
                "Earth & Soil": """The jewelry rests on natural earth — soil, clay, or packed ground with the organic quality of real outdoor terrain. The surface has visible texture — small particles, natural variation, the slight moisture that gives real earth its particular color and density. The jewelry settles into the earth with genuine weight — pressing slightly into the surface, the contact points showing the fine granular detail of the material around them.""",
                "Ice & Frost": """The jewelry rests on or within ice or frost — a surface defined by cold, clarity, and the optical behavior of frozen water catching light. The ice surface may be clear and deep, or frosted and crystalline. Light passes through or reflects off the ice with a particular blue-white quality. Silver and white gold find their most natural environment here. Even warm gold reads differently against this coolest of surfaces.""",
            }),
            ("light-direction", "LIGHT DIRECTION", {
                "Raking Side Light": """Light enters from a low, extreme side angle — nearly parallel to the surface rather than above it. The raking angle makes every surface texture visible and dramatic. The surface becomes a landscape under raking light. The jewelry rises from this textured landscape and catches the side light on its vertical surfaces — the lit edge sharp and bright, the shadow side deep and committed.""",
                "Overhead Sun": """Light falls from directly above — a strong vertical source that illuminates the top surfaces of everything in the frame while allowing the sides to fall into natural shadow. The contact shadows of the jewelry fall compressed and centered beneath it. The top faces of gemstones and metal surfaces receive the full intensity of the overhead source — bright, direct, and precise.""",
                "Golden Hour": """Light has the quality of late afternoon sun — warm, directional, and deeply colored. The light source is low on the horizon, casting long shadows across the surface in a single direction. Everything the light touches takes on warmth. Gold jewelry becomes richer and more saturated. Silver picks up warmth it doesn't naturally have.""",
                "Diffused Overcast": """Light comes from the entire sky at once — soft, directionless, and completely even. No single light source creates a defined shadow direction. The surface and the jewelry are both revealed without drama — every detail visible, every surface readable. The atmosphere is calm, cool, and contemplative.""",
                "Backlit": """The light source is behind the jewelry and the surface — the camera faces into the light. The edges of the jewelry and any upstanding elements of the surface are rimmed with bright separation light. Translucent surface elements — thin leaves, water, frosted ice, fine fabric — glow from within when backlit, becoming luminous rather than opaque.""",
            }),
            ("shadow-play", "SHADOW PLAY", {
                "None": """No shadow element is introduced beyond what the light direction naturally produces on the jewelry and its immediate surface. The image is defined by light and material — shadow is a byproduct, not a subject.""",
                "Leaf & Nature Shadow": """Shadows of botanical elements — leaves, branches, grasses, flowers, or fronds — fall across the surface and the jewelry from outside the frame. The botanical elements themselves are not visible — only their shadows are present. The shadows are soft-edged if the botanical is close to the surface, crisp-edged if it is far above. The presence of nature is felt without being seen.""",
                "Geometric Shadow": """A shadow with clean, architectural edges falls across the surface and jewelry — cast by a window frame, a wall edge, a blind, a structural element just outside the frame. The shadow is straight-edged and deliberate — a graphic element as composed as the jewelry itself. The geometric shadow creates a secondary compositional structure across the image.""",
                "Long Directional": """The jewelry casts a long shadow across the surface in a single direction — the shadow extending significantly further than the jewelry itself. The shadow is the jewelry's signature — its shape, its height, its structure all readable in the shadow it casts. On textured surfaces the shadow follows the surface contours. The shadow and the jewelry compose the image together.""",
            }),
            ("color-temperature", "COLOR TEMPERATURE", {
                "Warm Gold": """The light carries a distinctly warm, golden color temperature — amber and orange tones saturate every surface. The warmth is natural and atmospheric. Gold jewelry amplifies and resonates with this temperature. Silver jewelry takes on an unexpected warmth.""",
                "Cool Neutral": """The light is clean and neutral — neither warm nor cool, a precisely balanced color temperature that renders every material with complete accuracy. No color cast influences the surfaces. The jewelry reads at its truest — gold is exactly gold, silver is exactly silver, gemstones are exactly their own color.""",
                "Deep Contrast": """The light is high in contrast — the difference between the brightest highlights and the deepest shadows is dramatic and committed. The color temperature may be warm or cool — the AI selects the most flattering for the jewelry — but in either case the contrast is the dominant quality. Everything reads with maximum material intensity.""",
                "Soft Muted": """The light is low in contrast and slightly desaturated — colors are present but understated, tones gentle and close together. The atmosphere is quiet and contemplative. The jewelry reads with refinement rather than drama. The surface beneath settles into a soft tonal field that supports the jewelry without competing.""",
            }),
            ("composition", "COMPOSITION", _COMPOSITION),
            ("brand-accent", "BRAND ACCENT", {
                "Brand Accent": {"prompt": """The color [HEX] is present somewhere in the image as a natural element — not as a background, not as an overlay, but as the genuine color of something that already exists in the scene. The AI finds the most natural and beautiful carrier for this color within the selected surface and light environment. The color [HEX] appears as if it was always going to be there — discovered rather than applied. It is the brand's presence in the image — quiet, intentional, and entirely belonging.""", "has_color": True},
            }),
        ],
    },
    "arranged": {
        "atmosphere": """Multiple pieces, one moment. Each piece fully itself, fully in relationship with every other. The arrangement is a decision — deliberate, intentional, complete. The collection as a single composed statement.""",
        "categories": [
            ("arrangement-style", "ARRANGEMENT STYLE", {
                "Clean Grid": """The pieces are arranged in a geometric, deliberately spaced grid formation — rows and columns with consistent intervals. The grid is not mechanical — slight natural variation in position and angle keeps it from feeling computer-generated. Each piece occupies its own defined zone — no piece overlaps another, no piece crowds its neighbor. The negative space between pieces is equal and intentional.""",
                "Organic Scatter": """The pieces are arranged with deliberate organic randomness — as if placed one at a time by a human hand without measuring or overthinking. No two pieces are at the same angle. No two pieces are equidistant from each other. The arrangement has the quality of something that happened rather than something that was constructed. Despite its apparent casualness the scatter is composed — every piece is fully visible, no piece hides behind another.""",
                "Radial": """The pieces radiate outward from a central point — arranged like the spokes of a wheel or the petals of a flower, each piece pointing away from the shared center. The central point may be empty — a deliberate negative space — or occupied by the most significant piece. The radial arrangement creates a sense of movement and expansion — the eye travels from the center outward along each piece and returns.""",
                "Linear": """The pieces are arranged along a single line or gentle diagonal — one after another in a deliberate sequence. The line may be perfectly horizontal, perfectly vertical, or at a diagonal the AI determines creates the most dynamic composition. The spacing is consistent but not mechanical. Each piece is angled slightly differently from its neighbors — the same line, different orientations.""",
                "Overlapping": """The pieces are arranged with deliberate overlap — one piece partially covering another, layers of jewelry creating depth and dimension. The overlap is intentional and specific — the pieces that overlap do so at a single defined point or edge, never merging or becoming confused. The piece on top is completely visible. The piece beneath is partially visible — enough to understand its full form.""",
                "Hero & Supporting": """One piece is the clear compositional hero — positioned centrally or prominently, larger in the frame, more fully lit, the unambiguous focus of the entire arrangement. The remaining pieces are supporting — positioned around the hero, contributing to the composition without competing with it. The supporting pieces are fully visible and fully readable — they exist in conversation with the hero piece, giving it context and company.""",
            }),
            ("surface", "SURFACE", {
                "Studio Color": {"prompt": """The arrangement is presented against a background built entirely around [HEX]. That color saturates the field behind and beneath the jewelry completely — rich, deep, and intentional. Every piece reads clearly against the color field — contrast between metal and [HEX] is preserved across all pieces simultaneously. No gradients, no texture. Pure color as the stage for the entire collection.""", "has_color": True},
                "Pure White": """A pure white seamless field behind and beneath the arrangement — no background detail, no environmental context, nothing competing with any piece. Each piece is equally revealed — the white field giving every piece the same clean, neutral stage.""",
                "Soft Gray": """A neutral mid-gray field behind and beneath the arrangement — balanced and unbiased, neither amplifying nor suppressing any piece's own color or tone. The gray creates gentle separation between each piece and the background, allowing the arrangement itself to be the entire subject.""",
                "Deep Black": """A near-black field absorbs everything around the jewelry — each piece in the arrangement emerges from darkness with individual intensity. The black field makes every material surface read with maximum luminosity. The arrangement feels precious and rare.""",
                "Warm Ivory": """A warm ivory field behind and beneath the arrangement. Gold jewelry resonates with particular richness. The arrangement reads as warm and precise — a collection presented with quiet confidence.""",
                "Silk": """The arrangement rests on silk fabric — smooth, lustrous, and fluid. The fabric creates a secondary landscape of highlight and shadow beneath the pieces. Each piece settles into the silk with natural weight. The sheen of silk and the sheen of metal exist in continuous conversation across the arrangement.""",
                "Linen": """The arrangement rests on linen — matte, textured, naturally imperfect. The visible weave creates a tactile contrast against the precision of every piece. Each piece settles into the linen with genuine weight, the weave visible at every contact point.""",
                "Velvet": """The arrangement rests on velvet — deep, light-absorbing, and rich. The velvet surface creates dramatic contrast against the reflective surfaces of each piece — where the velvet absorbs, the metal reflects. The arrangement has a stage of maximum luxury.""",
                "Marble": """The arrangement rests on marble — smooth, cool, and veined with natural mineral patterns. The marble's veining creates an organic compositional element beneath the arrangement without competing with any piece. The polished surface may carry subtle reflections of the jewelry above.""",
                "Stone": """The arrangement rests on natural stone — rough, textured, and organically imperfect. The raw surface creates maximum contrast against the refined precision of every piece. Each piece's contact with the stone is honest and unforced.""",
                "Wood": """The arrangement rests on a wooden surface — the grain visible, directional, and full of natural warmth. The grain lines create natural compositional structure beneath the arrangement — leading the eye between pieces along the wood's own directional lines.""",
            }),
            ("lighting", "LIGHTING", _SHARED_LIGHTING),
            ("quantity", "QUANTITY", {
                "Pair": """The composition is built around exactly two pieces — a pair of earrings, two rings, two complementary pieces. The two pieces are in clear visual relationship with each other. If only one piece was uploaded, the composition presents it twice as a true pair would appear — with slight natural variation in angle and position. No additional jewelry is invented.""",
                "Small Collection": """The composition is built around three pieces — a precise edit that feels like the essential core of a collection. Three is the most compositionally dynamic number — it resists perfect symmetry while creating natural balance. If fewer than three pieces were uploaded, the composition adapts to the actual number present — it never invents additional jewelry.""",
                "Full Collection": """The composition is built around all uploaded pieces — up to four — presented together as a complete collection statement. Every piece is fully visible and fully readable within the arrangement. No piece is hidden behind another to the point of illegibility. The full collection as a unified world, each piece a chapter of the same story.""",
            }),
            ("color-palette", "COLOR PALETTE", {
                "Neutral & Clean": """The overall tonal world of the image is neutral and clean — white, pale grey, soft ivory, natural cream. No strong color competes with the jewelry. Every piece reads at its own truest color against a background that takes no position.""",
                "Rich & Dark": """The overall tonal world of the image is rich and dark — deep backgrounds, committed shadows, colors in their most saturated and deepest register. The darkness makes every piece in the arrangement read with maximum luminosity — the collection emerging from depth rather than sitting on a surface. Precious, intense, and deeply considered.""",
                "Warm & Earthy": """The overall tonal world of the image is warm and earthy — amber, terracotta, warm brown, dusty gold, natural ochre. The warmth saturates every surface and carries into the highlights on each piece. The collection reads as warm, grounded, and human.""",
                "Soft & Minimal": """The overall tonal world of the image is soft and minimal — low contrast, slightly desaturated, gentle and close in tone across the entire frame. Nothing shouts, everything belongs. The most editorial of all palette options.""",
            }),
            ("composition", "COMPOSITION", _COMPOSITION),
        ],
    },
    "on-display": {
        "atmosphere": """The form holds the jewelry the way a body holds it — with presence and intention. The jewelry is elevated, angled, presented. Everything the display form does is in service of the piece above it.""",
        "categories": [
            ("display-form", "DISPLAY FORM", {
                "Ceramic Bust": f"""The jewelry is presented on a ceramic bust — a clean, smooth, kiln-fired form representing the neck, collarbone, and upper chest of a human figure. The ceramic surface is matte or semi-matte. The form is classic and precise — the kind of display bust that has presented fine jewelry in the world's best stores for over a century. Its simplicity is its authority.

{_DISPLAY_FORM_ADAPTATION}""",
                "Stone Bust": f"""The jewelry is presented on a bust carved or formed from natural stone — limestone, marble, sandstone, or any natural mineral material. The stone surface is raw or lightly worked — visible grain, natural color variation. The combination of stone and jewelry is one of geological material meeting refined craft — two objects that both came from the earth, one raw, one transformed by human skill into something precise.

{_DISPLAY_FORM_ADAPTATION}""",
                "Abstract Form": f"""The jewelry is presented on an abstract sculptural form — an object that suggests the human body without representing it, or makes no reference to the body at all and simply presents itself as a considered three-dimensional object designed to hold the jewelry at the right height and angle. The abstract form may be organic or architectural. The AI selects the form that creates the most visually interesting relationship with the specific jewelry uploaded.

{_DISPLAY_FORM_ADAPTATION}""",
                "Geometric Plinth": f"""The jewelry is presented on a clean geometric block, pedestal, or architectural plinth — a precise, flat-topped form that elevates the jewelry above the surface beneath it. The plinth is architectural in its precision — clean edges, flat surfaces, consistent geometry. It may be a simple cube, a rectangular block, a cylinder, or a tapered column. Two designed objects, one presenting the other, both committed to their own form.

{_DISPLAY_FORM_ADAPTATION}""",
                "Draped Form": f"""The jewelry is presented on a form covered in draped fabric — a bust or sculptural shape whose hard structure is softened and humanized by textile. The fabric drapes naturally over the form beneath — following its contours, settling at its base. The fabric is a natural material — silk, linen, velvet, or cotton — in a neutral or intentional tone that complements the jewelry above.

{_DISPLAY_FORM_ADAPTATION}""",
                "Minimal Mannequin": """The jewelry is presented on a stripped-back human form — a mannequin reduced to its essential structural elements with no face, no hands, no identifying features. What remains is the architecture of a human torso and neck. The mannequin surface is clean and unified in tone — a single material and color that makes the jewelry the only point of visual complexity. The form presents the jewelry exactly as it would sit on a person — with the natural drape, the correct proportions, and the implicit promise of how it would feel to wear it. The most direct of all display forms — the jewelry one step away from the body it belongs on.""",
            }),
            ("display-color", "DISPLAY COLOR", {
                "Pure White": """The display form is pure white — clean, bright, and completely neutral. Against white, every metal tone and every gemstone color reads at maximum contrast and clarity.""",
                "Warm Beige": """The display form is warm beige — the color of natural linen, pale sand, or aged ivory. The warmth of the form carries into the jewelry above — gold reads richer, warm gemstones amplify. The overall image settles into a quiet, precise luxury.""",
                "Stone Gray": """The display form is stone gray — the neutral, mineral tone of concrete, slate, or pale granite. Neither warm nor cool, the gray form is the most color-accurate presenter. The gray form has the quiet authority of architectural material.""",
                "Matte Black": """The display form is matte black — a surface that absorbs light and creates maximum contrast against every metal tone and gemstone color above it. Against matte black, gold glows, silver shines, colored gemstones read with their deepest saturation.""",
                "Natural": """The display form retains its own natural material color — the actual tone of the ceramic, stone, fabric, or material it is made from, unmodified by paint or finish. The AI renders the form in the most authentic version of its own material — the particular warmth of fired clay, the cool gray of natural limestone, the specific ivory of undyed linen.""",
            }),
            ("scene", "SCENE", {
                "Studio Color": {"prompt": """The display form is presented against a background built entirely around [HEX]. That color saturates the field behind the form completely — rich, deep, and intentional. The display form stands clearly against the color field, the jewelry above it reading with complete contrast and clarity. The brand color is the environment.""", "has_color": True},
                "Pure White": """A pure white seamless studio environment behind and around the display form. The form is isolated in white — no background detail, nothing competing with the form or the jewelry it carries. Clinical, precise, and deeply authoritative.""",
                "Soft Gray": """A neutral mid-gray seamless environment behind and around the display form. The gray creates gentle separation between the form and the background without drama or distraction. The display form and the jewelry exist in focused isolation.""",
                "Deep Black": """A near-black environment absorbs everything around the display form. The form emerges from darkness with its own presence, the jewelry above it catching the controlled light source with intensity against the surrounding darkness.""",
                "Warm Ivory": """A warm ivory environment wraps around the display form. The warmth carries from the background into the highlights on both the form and the jewelry — the entire image exists in a warm, quiet register that communicates considered luxury without effort.""",
                "Soft Gradient": """A seamless gradient environment transitions gradually behind the display form — the AI determines the most flattering direction. The gradient gives the background quiet depth — the display form stands against a field that breathes rather than sits flat.""",
            }),
            ("lighting", "LIGHTING", _SHARED_LIGHTING),
            ("angle", "ANGLE", {
                "Front Facing": """The display form faces the camera directly — the full front of the form and the jewelry it carries presented to the lens in complete symmetry. The jewelry faces forward exactly as it would face a viewer in a store or gallery. Classic, authoritative, and completely legible. Shot on a Canon EOS R5, 85mm, f/4.0, ISO 100.""",
                "Slight Tilt": """The display form is turned slightly off its direct axis — perhaps 15 to 30 degrees from front facing. The slight turn introduces three-dimensionality — the side of the form becomes partially visible. The tilt is subtle enough that the jewelry remains fully readable — nothing is obscured by the angle. Shot on a Canon EOS R5, 85mm, f/4.0, ISO 100.""",
                "Profile": """The display form is rotated to a true 90 degree side profile — the full architectural silhouette of the form reads against the background as a single unbroken line from base to top. The camera faces the exact side of the form — not a three-quarter turn, not a slight angle, but a genuine profile where the front face of the display form is entirely turned away from the lens. What the camera sees is the form's silhouette — its depth, its thickness, its three-dimensional presence read as a composed shape against the background. Jewelry at the neck or collarbone — necklaces, pendants, chokers — is seen from the side in full depth: the chain's drape, the pendant's hang, the distance the piece sits from the form's surface. Shot on a Canon EOS R5, 85mm, f/4.0, ISO 100. The most sculptural of all angle options — the display form and its jewelry read as a single object in space.""",
                "Close Up": """The camera moves close to the display form — close enough that the jewelry fills the majority of the frame and the form beneath it exists only as immediate context. At this distance the jewelry's relationship with the form surface is completely visible — every contact point, every drape, every clasp point readable in full detail. Shot on a Canon EOS R5, 100mm macro, f/4.5, ISO 100.""",
                "Full View": """The camera pulls back far enough to show the complete display form — from its base to its top — with the jewelry in full context and the environment visible around the form. The full form is the subject — the display form as an object in a space, the jewelry as what elevates that object from furniture to something precious. Shot on a Canon EOS R5, 35mm, f/8.0, ISO 100.""",
            }),
        ],
    },
}


def is_v52_pure_jewelry_style(style: dict[str, str] | None) -> bool:
    if not style:
        return False
    version = (style.get("public_version_key") or "").strip().lower()
    style_type = (style.get("style_type") or "").strip()
    return version == V52_PROMPT_VERSION or style_type in _PURE_JEWELRY_STYLES


def _normalize_type(value: str) -> str:
    return _TYPE_ALIASES.get(value, value)


def _resolve_type(items: Iterable[GenerationItem] | None, style: dict[str, str]) -> str:
    for item in items or []:
        label = (item.type or "").strip()
        if label:
            return _normalize_type(label)
    return _normalize_type((style.get("product") or "").strip())


def _resolve_size(items: Iterable[GenerationItem] | None) -> str:
    for item in items or []:
        label = (item.size or "").strip()
        if label:
            return label
    return ""


def _option_prompt(option_entry: object, color_hex: str) -> str:
    if isinstance(option_entry, str):
        return option_entry
    if isinstance(option_entry, dict):
        return str(option_entry.get("prompt", "")).replace("[HEX]", color_hex)
    return ""


def build_v52_pure_jewelry_prompt(style: dict[str, str] | None, items: list[GenerationItem] | None) -> str:
    style = style or {}
    style_type = (style.get("style_type") or "").strip()
    config = _PURE_JEWELRY_STYLES.get(style_type)
    color_hex = (style.get("studioColorHex") or _DEFAULT_COLOR_HEX).upper()

    parts = [f"HERO\n{_HERO}"]

    if config:
        parts.append(f"\nATMOSPHERE\n{config['atmosphere']}")

    item_type = _resolve_type(items, style)
    if item_type in _TYPE_PROMPTS:
        parts.append(f"\nJEWELRY TYPE: {item_type}\n{_TYPE_PROMPTS[item_type]}")

    size = _resolve_size(items)
    if size in _SIZE_PROMPTS:
        parts.append(f"\nJEWELRY SIZE: {size}\n{_SIZE_PROMPTS[size]}")

    if config:
        for category_id, category_name, options in config["categories"]:
            selected = (style.get(category_id) or "").strip()
            if not selected or selected == "None":
                continue
            option_entry = options.get(selected)
            if option_entry is None:
                continue
            prompt = _option_prompt(option_entry, color_hex)
            if prompt:
                parts.append(f"\n{category_name}: {selected}\n{prompt}")

    parts.append(f"\n{_QUALITY}")
    return "\n".join(parts)
