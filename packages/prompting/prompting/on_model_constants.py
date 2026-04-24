_ON_MODEL_BASE_HERO = (
    "Ultra realistic luxury jewelry campaign photograph of a fashion model wearing the uploaded "
    "jewelry, captured by a world-class fashion photographer as a high-end jewelry advertising "
    "campaign."
)

_ON_MODEL_BASE_MODEL = (
    "Natural human appearance with high-end editorial realism, healthy glowing skin with visible "
    "micro-texture, natural skin imperfections including pores, fine lines, and subtle "
    "variations, subtle peach fuzz and fine facial hairs catching light, realistic skin "
    "reflectivity with soft natural highlights on cheekbones and nose, even but non-uniform skin "
    "tone with organic variation, naturally defined facial features without exaggeration, minimal "
    "refined editorial makeup enhancing natural beauty, soft skin transitions without artificial "
    "smoothing, authentic human presence with lifelike detail, slight natural asymmetry in facial "
    "features, calm confident expression with subtle emotional depth, subtle natural variation in "
    "facial features, skin tone, and structure across generations."
)

_ON_MODEL_BASE_JEWELRY = (
    "Jewelry is always fully visible and unobstructed, no elements covering or hiding the "
    "jewelry, clear separation between jewelry and surrounding elements, jewelry edges remain "
    "sharp and readable, high-end jewelry photography focus, natural integration of the jewelry "
    "within the composition, clear visual emphasis on the jewelry as the focal point, extremely "
    "sharp jewelry detail, macro-level craftsmanship visibility, realistic reflections on metal "
    "surfaces, subtle specular highlights enhancing form, accurate material rendering (metal, "
    "gemstones, textures), balanced contrast preserving jewelry visibility, no distortion or "
    "deformation of the jewelry."
)

_ON_MODEL_BASE_STYLE = (
    "Professional photo post-processing, balanced exposure and dynamic range, refined highlight "
    "and shadow control, natural color rendering, accurate white balance, subtle contrast "
    "enhancement, fine detail sharpening without over-processing, realistic texture "
    "preservation, natural skin tones without smoothing artifacts, clean high-end photography "
    "finish, no artificial or over-processed look."
)

_ON_MODEL_RULES = (
    "Clean and controlled high-end beauty and commercial jewelry output. Preserve visibility of "
    "jewelry edges and material qualities at all times. Maintain realistic skin texture and "
    "natural human presence. No extreme pose or gesture clipping on hands, face, jewelry, or "
    "garment details. Avoid duplicate jewelry visibility errors, distorted reflections, deformed "
    "anatomy, warped accessories, or occlusion between jewelry and clothing. Ensure the final "
    "output reads as premium fashion photography, not AI-generated artifact imagery."
)

_ON_MODEL_V45_HERO = """Ultra-realistic editorial jewelry photograph. The standard is Vogue, Harper's Bazaar, AnOther Magazine — cinematic depth, honest light, genuine human presence.

Skin has real texture. Fabric behaves naturally. Jewelry is rendered with material truth: accurate metal reflectivity, honest gemstone behavior, sharp edges and fine detail. No artificial sparkle. No glow effects.

The only jewelry in the image is what was uploaded — maximum 4 pieces. Nothing added, nothing invented, nothing assumed. This rule is absolute and overrides every other creative decision.

The composition is not always a portrait. The face is not always the subject. The camera finds whatever is most alive in the frame — a shoulder, a hand, a back, a silhouette, a body mid-motion, a detail of fabric and skin. The model does not always face the camera. The camera does not always face the model. What makes the image work is human truth, not human faces.

The image feels taken, not generated. Every frame should feel like it could have been the unexpected shot from a roll of film — the one the photographer almost missed, and almost didn't keep, and couldn't stop looking at."""

_ON_MODEL_V45_MODEL_BASE = """Skin is photographically real — visible pores, subtle fine lines, natural tone variation across the face and body. No smoothing, no retouching, no porcelain finish.

Skin imperfections are limited strictly to what a camera naturally captures: texture variation, contour shadow, organic color shift. No added moles, no blemishes, no artificially placed marks of any kind.

Specular highlights fall naturally on the cheekbones, nose bridge, and collarbone. Peach fuzz catches directional light. Skin reflectivity is neither matte nor luminous — it behaves like real skin under real light.

Subtle natural asymmetry preserved. The model feels inhabited, not rendered."""

_ON_MODEL_V45_QUALITY = """QUALITY CONTROL — ALL RULES ARE ABSOLUTE:

JEWELRY: 1) Always fully visible and unobstructed. 2) Complete material accuracy — realistic reflectivity, accurate gemstones, sharp edges. No sparkle effects, no lens flare. 3) Edges always sharp and readable. 4) Only the uploaded jewelry appears — nothing added, invented, or assumed. This cannot be overridden.

SKIN: 5) Natural photographic realism — pores, texture, organic tone. No smoothing. 6) No moles, blemishes, or added skin marks. 7) Hands with correct anatomy — natural finger count, realistic joints. No distortion. 8) Eyes symmetrical and natural — no artificial glow or unnatural enhancement.

COHERENCE: 9) All presets work as a coherent whole. 10) Camera framing is never overridden by pose or composition. The face is never the automatic center of the frame. 11) Selected scene is always present and readable. 12) Hair never accidentally covers the jewelry zone.

TECHNICAL: 13) No AI artifacts. 14) Background coherent and continuous. 15) Fabric behaves with real physical laws. 16) Lighting physically coherent.

FINAL: 17) Would the photo editor of Vogue, Harper's Bazaar, or AnOther Magazine accept this as a jewelry campaign image? If not — it is not finished."""

_ON_MODEL_PROMPT_VERSION_V2 = "v2"
_ON_MODEL_PROMPT_VERSION_V45 = "v4.5"

_ON_MODEL_MAPPING_V2 = {
    "background": {
        "Blue Hour Editorial": "Portrait captured during blue hour twilight, deep navy evening sky, subtle gradient dusk atmosphere, soft blurred horizon in the background, cool ambient evening tones, cinematic editorial outdoor setting, luxury fashion campaign environment.",
        "White Studio": "Minimal white photography studio, clean white background with subtle gradient depth, soft shadow transitions behind the subject, professional studio environment, editorial product photography setting, focus entirely on the model and jewelry.",
        "Studio Color (Dynamic)": "Luxury studio background using the color {color}, soft gradient studio backdrop, subtle shadow depth behind the subject, professional fashion studio lighting environment, editorial jewelry campaign setting, background color softly diffused with depth.",
        "Coastal Luxury": "Luxury coastal environment, soft ocean horizon in the distance, sunlight reflecting on water, warm natural outdoor lighting, cinematic seaside atmosphere, luxury lifestyle campaign setting.",
        "Architectural Minimal": "Modern architectural environment, clean stone or concrete surfaces, minimalist geometric background, soft natural shadows, luxury contemporary architecture, high fashion editorial setting.",
        "Sunlit Resort": "Luxury resort environment, bright natural sunlight, elegant outdoor terrace or poolside atmosphere, sunlit architectural elements, warm luxury lifestyle aesthetic, high-end vacation campaign setting."
    },
    "emotion": {
        "Calm Confidence": "Calm confident expression, steady gaze, relaxed facial muscles, subtle luxury campaign energy, refined editorial presence.",
        "Soft Warmth": "Soft warm expression, gentle eyes, subtle natural smile, approachable elegance, relaxed refined facial expression.",
        "Mysterious": "Subtle mysterious expression, slightly distant gaze, editorial intrigue, controlled refined facial expression, quiet confidence.",
        "Bold Presence": "Bold confident expression, strong eye contact, commanding editorial presence, refined high-fashion attitude, powerful model energy.",
        "Dreamy": "Dreamy elegant expression, soft distant gaze, delicate editorial mood, gentle refined facial expression, romantic fashion atmosphere.",
        "Joyful Glow": "Subtle joyful expression, soft natural smile, warmth in the eyes, luxury lifestyle campaign energy, bright refined presence."
    },
    "hair": {
        "Natural Hair": "Hair styled naturally according to the model's hairstyle, natural hair flow, realistic hair texture, subtle movement in the hair, soft flyaway strands catching light.",
        "Collected Hair": "Hair styled in a clean collected look, pulled back or structured away from the face, natural hair texture preserved, subtle flyaway for realism, refined and controlled silhouette.",
        "Behind Ear": "Hair gently tucked behind the ear, natural hair flow maintained, soft strands framing the face, realistic hair texture, subtle flyaway hairs catching light.",
        "Soft Wind": "Hair moving gently in a soft breeze, natural hair motion, soft strands flowing naturally, realistic hair texture and movement, editorial fashion atmosphere.",
        "Side Sweep": "Hair swept softly to one side, natural volume and texture, soft strands framing the face, editorial hair styling, subtle movement in the hair."
    },
    "outfit": {
        "Minimal Luxury": "Minimal luxury fashion styling, clean modern clothing, elegant contemporary silhouette, refined editorial aesthetic, neutral tones, natural fabric folds and realistic garment drape.",
        "Tailored Blazer": "Modern tailored blazer styling, structured contemporary silhouette, clean editorial fashion look, luxury minimalist styling, refined fashion campaign wardrobe, natural fabric texture and folds.",
        "Soft Elegance": "Soft elegant fashion styling, flowing luxury fabrics, delicate contemporary silhouette, refined feminine aesthetic, editorial fashion wardrobe, natural fabric movement and texture.",
        "High Fashion": "High fashion editorial styling, modern statement wardrobe, fashion-forward contemporary silhouettes, luxury runway-inspired aesthetic, bold upscale styling with varied modern garments, elevated fashion pieces such as sculptural outerwear, sleek contemporary tops, technical fabrics, metallic or matte textures, and directional silhouettes, unexpected but refined styling choices, realistic texture, folds, and construction details, avoid repetitive blazer or business wear looks.",
        "Effortless Chic": "Effortless casual styling, modern relaxed clothing, lightweight and natural fabrics, loose comfortable silhouettes, understated everyday fashion, clean minimal styling with a natural feel, soft fabric movement and realistic texture, modern casual wardrobe with a cool contemporary aesthetic, avoid overly formal or structured fashion."
    },
    "pose": {
        "Editorial Portrait": "Model standing in an elegant editorial portrait posture, body slightly angled toward the camera, relaxed shoulders, refined fashion model presence, natural confident stance, timeless luxury campaign composition, natural fashion model body language.",
        "Over Shoulder": "Model turning slightly over the shoulder, natural body rotation, soft gaze toward the camera, editorial fashion posture, subtle movement captured in the pose, dynamic portrait composition, natural fashion model body language.",
        "Profile Pose": "Model positioned in an elegant side profile, head slightly turned, refined facial posture, clean silhouette composition, editorial fashion portrait style, timeless luxury campaign framing, natural fashion model body language.",
        "Close Editorial": "Tight editorial portrait framing, camera positioned close to the model, intimate fashion campaign composition, subtle head angle, relaxed facial posture, clean minimal portrait styling, natural fashion model body language.",
        "Natural Gesture": "Model making a soft natural gesture with the hands, relaxed body posture, organic movement captured naturally, editorial fashion body language, elegant casual motion, luxury lifestyle campaign composition, natural fashion model body language.",
        "Fashion Movement": "Model captured during subtle natural movement, fluid body posture, dynamic fashion model body language, soft motion in the pose, editorial campaign energy, natural elegance in motion.",
        "Relaxed Luxury": "Model in a relaxed luxury fashion pose, natural confident posture, soft body alignment, elegant effortless presence, editorial campaign composition, refined modern model attitude, natural fashion model body language.",
        "Interactive Product Pose": "Natural interaction with the product integrated into the pose, hands, arms, or body subtly engaged in organic positioning, expressive yet controlled body language, soft contact gestures adding visual interest, effortless movement and natural positioning, editorial lifestyle-inspired composition, dynamic framing with slight asymmetry, pose feels candid yet intentionally composed, subtle shifts in posture creating variation across generations, body positioning enhances visibility without feeling staged.",
        "Full / Waist Fashion": "Full-body or waist-up framing variation, model positioned within the environment with visible spatial context, randomized framing between full-body and waist-up composition, natural standing or relaxed body positioning, balanced posture with subtle weight shift [one leg slightly dominant], arms positioned naturally [resting, slightly bent, or interacting with body], editorial fashion presence with relaxed confidence, composition allows visibility of outfit and body silhouette, pose feels effortless and unstaged, slight variation in stance and positioning across generations, framing adapts organically to the scene while maintaining subject clarity."
    },
    "lighting": {
        "Soft Studio Light": "Large diffused key light softly illuminating the subject, subtle secondary fill light balancing shadows, very gentle shadow transitions across the face, clean and even studio lighting setup, soft natural highlights on skin, controlled reflections on jewelry surfaces, minimal contrast for a polished commercial look.",
        "Cinematic Key Light": "Soft directional key light shaping facial features, subtle secondary fill light softening deep shadows, gentle rim light separating the subject from the background, balanced multi-light cinematic setup, controlled contrast with depth and dimension, warm highlights on skin with cooler ambient tones, editorial lighting atmosphere with dramatic softness.",
        "Natural Window Light": "Soft natural light entering from one side, subtle ambient bounce light filling shadows, organic light falloff across the face and body, naturally uneven but balanced illumination, realistic skin highlights with soft transitions, gentle reflections on jewelry from natural light sources, authentic lifestyle lighting feel.",
        "Golden Hour Glow": "Low angle warm key light mimicking sunset light, soft secondary fill light maintaining facial detail, subtle rim light from behind enhancing hair and silhouette, warm golden highlights on skin, soft elongated shadows with smooth falloff, natural glow on jewelry surfaces, cinematic sunset lighting atmosphere.",
        "Jewelry Sparkle Light": "Precise multi-light setup designed for jewelry emphasis, controlled directional highlights on metal surfaces, sparkling reflections across gemstones and edges, subtle fill light preserving skin realism, fine specular highlights enhancing brilliance, clean contrast between light and shadow areas, luxury product photography lighting effect.",
        "High Fashion Contrast": "Dramatic fashion lighting, strong directional key light creating sculpted shadows, minimal fill light preserving deep contrast, subtle edge or rim light separating the silhouette, bold contrast between light and shadow, editorial high-fashion lighting style, sharp controlled highlights on reflective surfaces, luxury runway campaign atmosphere."
    },
    "camera": {
        "Editorial Portrait": "Shot on a professional full frame camera, 85mm portrait lens, tight framing on the subject, compressed perspective with natural proportions, subject fills most of the frame, shallow depth of field with soft background blur, clean portrait composition, high dynamic range.",
        "Close-Up Detail": "Shot on a macro or close-up lens, tight framing emphasizing fine details, subject area fills most of the frame, very shallow depth of field, sharp focus on textures and small elements, soft background blur with strong falloff, intimate product-focused composition, high dynamic range.",
        "Beauty Macro": "Shot on a macro lens, extreme close-up framing, very tight crop focusing on a small area of the subject, subject area dominating the frame, ultra high detail showing fine textures and micro surface elements, sharp focus on a precise focal point, very shallow depth of field with soft falloff, intimate high-detail composition, high dynamic range.",
        "Cinematic Depth": "Shot on a cinema-style camera, 50mm lens perspective, subject placed within the environment, wider framing showing surroundings, subject not filling the entire frame, natural depth and spatial separation, cinematic composition with visible background context, moderate depth of field, high dynamic range.",
        "Fashion Wide Angle": "Shot on a wide angle lens, camera positioned close to the subject, slight perspective distortion exaggerating proportions, dynamic framing with depth, subject appears larger relative to the frame, editorial fashion composition, environment slightly visible with depth, high dynamic range.",
        "Low Angle Perspective": "Camera positioned below the subject, upward shooting angle, subject appears taller and more dominant, strong perspective lines, editorial fashion dominance, dynamic visual tension.",
        "iPhone Realism": "Shot on a modern smartphone camera, natural handheld framing, slight lens distortion typical of mobile cameras, deeper depth of field compared to professional cameras, subtle computational photography look, balanced HDR with slightly lifted shadows, realistic sharpness without studio perfection, authentic real-life capture feel."
    },
    "image_style": {
        "Natural Balanced": "Natural color grading, balanced contrast, soft highlight roll off, clean shadow detail, realistic tones across the image, subtle sharpening, no heavy stylization.",
        "Soft Luxury": "Soft refined color grading, slightly lifted highlights, gentle contrast with smooth transitions, clean luminous skin tones, subtle glow on highlights, polished luxury finish.",
        "High Contrast": "Strong contrast enhancement, deeper shadows with bright highlights, crisp tonal separation, increased clarity and sharpness, bold but controlled image depth.",
        "Warm Editorial": "Warm color grading with golden tones, slight warmth in highlights, soft shadow depth, cinematic tone balance, natural but stylized warmth.",
        "Cool Editorial": "Cool toned color grading, slight blue or neutral tint in shadows, clean modern tonal balance, controlled contrast, minimalist contemporary finish.",
        "Film Noir": "Black and white color grading, high contrast with deep blacks, bright highlights with sharp tonal separation, subtle film grain texture, dramatic shadow depth, cinematic monochrome finish.",
        "Grainy Film": "Subtle film grain across the image, slightly desaturated tones, soft contrast curve, organic texture in shadows and highlights, film-like photographic finish."
    },
    "jewelry": {
        "Earring": "Subtle head positioning enhancing natural visibility, delicate light interaction around facial contours, fine detail clarity in small-scale elements.",
        "Necklace": "Natural alignment with body posture, soft interaction with skin and fabric, clear readability of central placement.",
        "Pendant": "Natural alignment with body posture, soft interaction with skin and fabric, clear readability of central placement.",
        "Choker": "Natural alignment with body posture, soft interaction with skin and fabric, clear readability of central placement.",
        "Ring": "Natural hand positioning within the composition, fine detail clarity in small surfaces, precise reflections on polished metal.",
        "Bracelet": "Natural wrist positioning within the frame, subtle interaction with movement and pose, clean visibility of circular forms and surfaces.",
        "Watch": "Natural wrist positioning within the frame, subtle interaction with movement and pose, clean visibility of circular forms and surfaces.",
        "Glasses": "Accurate alignment with facial structure, clean reflections on lenses without distortion, sharp detail on frame materials.",
        "Brooch": "Natural placement on clothing surfaces, clear contrast against fabric textures, sharp detail in small decorative elements.",
        "Hair Clips": "Natural integration within hairstyle, clear separation from hair through light, fine detail visibility across intricate elements.",
        "Headpieces": "Natural integration within hairstyle, clear separation from hair through light, fine detail visibility across intricate elements.",
        "Tiara": "Natural integration within hairstyle, clear separation from hair through light, fine detail visibility across intricate elements.",
        "Cufflinks": "Natural integration with clothing structure, precise detail visibility in small metallic forms, clean reflections on polished surfaces.",
        "Anklet": "Natural integration with body movement, soft interaction with skin and light, clear readability of delicate forms.",
        "Body Chain": "Natural integration with body movement, soft interaction with skin and light, clear readability of delicate forms."
    }
}

_ON_MODEL_MAPPING_V45 = {
    "background": {
        "Studio Color": "A controlled studio built entirely around {color}. That color saturates the background completely — rich, deep, intentional. Soft directional key light sculpts the subject while {color} holds at full depth behind her. The jewelry reads clearly against the color field — contrast between metal and {color} is always preserved. No gradients, no texture. Pure color as environment.",
        "White Studio": "Pure white seamless — no background detail, nothing competing. Light wraps evenly, maintaining facial and material dimension without harsh shadow. Clinical, precise, editorial. The jewelry has nowhere to hide and nowhere to be hidden.",
        "Dark Studio": "A near-black studio that absorbs light completely. A single controlled source sculpts the subject from one side — dramatic ratio, committed shadow. Skin and metal emerge from darkness. The jewelry catches the key light like a lit edge against deep black. The image feels like a film still.",
        "Blue Hour": "The transitional moment between daylight and dark — the sky a deep gradient of navy, cobalt, and indigo. Light is cool, directional, and layered. The environment is felt rather than seen — background soft and out of focus. The jewelry catches the cool ambient light with quiet intensity — metal reading crisp and precious against the depth of the blue world around it.",
        "Open Sky": "A vast open sky — deep, clean blue stretching across the entire background, broken only by soft natural clouds catching the light. The clouds are beautiful and dimensional — alive with depth and movement. The atmosphere feels boundless and clean. The jewelry becomes the only grounded element in a frame full of air and light.",
        "Desert Light": "Arid landscape — fine sand, dry golden grass, pale mineral rock. The sun is strong and directional, hard shadows cutting across skin and metal alike. Amber, bone white, burnt sienna. The harshness of the environment against the refinement of the jewelry is the tension that makes the image work.",
        "Coastal Cliffs": "A dramatic coastal environment high above water. Expansive sky dominates the background — light transitional, shifting between clear and overcast, warm and cool. Wind implied through movement in hair and fabric. Vast, clean, emotionally elevated. The jewelry feels like a private statement against an immense world.",
        "Forest Shade": "Dense organic green — large leaves, filtered canopy light, shadow pockets broken by sharp shafts of sun. Warm spots and cool shadows move across the subject. Deep green, forest brown, gold. Private and immersive. The jewelry catches individual shafts of light against organic darkness.",
        "Stone Terrace": "Bleached limestone, worn terracotta, ancient plaster catching side-raking sun. Shadows crisp and directional. Warm ivory, sand, dusty gold. Unhurried and quietly luxurious — a Mediterranean courtyard, a sun-warmed wall. The environment breathes warmth into the jewelry without competing with it.",
        "Raw Concrete": "Raw architectural exterior — thick concrete forms, geometric shadow lines, textured walls. Cool indirect light from open sky. Hard shadow edges cross the frame deliberately. The coldness of the material against the refinement of the jewelry is the defining tension.",
        "Evening Glow": "Dim, warm evening interior. Candlelight or warm practical sources glow just outside the frame. The light is golden, flickering in quality, deeply directional. Textured walls catch the light unevenly. Deep amber, shadow brown, warm gold. The jewelry glows with warmth rather than brilliance.",
        "Warm Interior": "A refined interior — window frame, wall texture, wooden surface, furniture softly visible behind. Warm light enters from one side through a large window, casting a gentle gradient across the subject. Ivory, timber, aged plaster, natural linen. A life being lived rather than a set being dressed.",
    },
    "emotion": {
        "Calm Confidence": "Quiet inner certainty — no performance, no effort, no need to prove anything. Complete stillness. The emotional register of someone who already knows the answer before the question is asked.",
        "Quiet Intensity": "Concentrated and deeply present — not aggressive, but focused. Something is happening beneath the surface that the viewer cannot fully read. Magnetic without explanation.",
        "Soft Warmth": "Genuine approachable warmth — not a commercial smile, but a real human glow. The emotional register of someone caught in a genuinely good moment. Effortlessly human.",
        "Bold Presence": "The model owns the frame completely. Commanding and unapologetic — high-fashion power that feels earned, not performed. Strength expressed through complete stillness.",
        "Mysterious": "Deliberately unreadable. The expression withholds more than it reveals — a depth the viewer cannot access. Like walking into the middle of a private thought.",
        "Ease": "Completely comfortable in her own skin and her own space — no charge, no performance, no awareness of being watched. The feeling of someone who has stopped trying and found something better on the other side of effort.",
        "Joyful": "Genuinely luminous — not a posed smile but a real brightness that seems caught rather than directed. Completely unguarded. Jewelry worn as part of a life being fully lived.",
        "Detached Cool": "Entirely self-contained. Editorial and slightly aloof — the cool that defines fashion's most iconic imagery. The model exists in her own world entirely. The viewer is only observing from a distance.",
    },
    "hair": {
        "Natural": "Hair falls exactly as it naturally would — unstyled, authentic to its own texture and weight. In outdoor scenes it responds to ambient air with subtle organic movement. In studio it settles with gravity. Individual strands behave independently — no artificial smoothness, no uniform flow. Lived-in and real.",
        "Slicked Back": "Hair pulled completely from the face, held close to the head — smooth, controlled, architectural. Both ears fully exposed. The neck and jaw unobstructed. The surface catches light as a single continuous plane. No flyaways, no volume, no loose strands.",
        "Swept Side": "Hair swept deliberately to one side — falling across one shoulder, leaving the opposite ear and neck completely exposed. The exposed side is always the jewelry side. The swept mass falls with natural weight. The contrast between the full side and the bare side draws the eye toward the jewelry.",
        "Behind Ear": "Hair gently tucked behind one or both ears — deliberate but casual, as if done in a private moment rather than for a camera. Both ears and jewelry fully exposed. The rest of the hair falls naturally around the tuck point.",
        "Hair Bun": "Hair gathered at the back or top of the head in a soft, natural bun — organic texture, loose strands, natural imperfection. Not a perfect geometric shape. Both ears and the full neck exposed. Face-framing pieces fall naturally at the temples and neckline.",
        "Wind Motion": "Hair caught in active, directional movement — lifted and flowing as a coherent mass, individual strands separating at the edges. The jewelry side of the face remains visible throughout. In studio environments, movement is subtle and implied — soft displacement at the hair's perimeter, as if the model has just stepped in from outside.",
    },
    "outfit": {
        "Quiet Luxury": "Understated and premium — cashmere, silk, fine linen, soft wool. Clean, considered silhouettes. Ivory, stone, camel, slate, warm white. Fabric drapes with weight, creases where the body moves. Nothing competes with the jewelry.",
        "Casual Cool": "Contemporary and effortless — denim, soft cotton jersey, oversized basics. Relaxed without being shapeless. White, light grey, faded indigo, washed black, natural ecru. The fabric feels lived-in and authentic. The jewelry sits against this casualness with natural contrast — elevated but entirely at home.",
        "Streetwear": "Oversized silhouettes, clean technical fabrics, urban layering — hoodies, bombers, wide-leg trousers. The proportions are considered, the oversizing deliberate. Clean monochrome or bold single color. Fine metal against raw street-level material is a specific kind of modern luxury.",
        "Sportswear": "Clean athletic wear — fitted technical fabrics, smooth performance materials. Sports bras, fitted tanks, seamless knits. Black, white, slate, deep navy, muted olive. High skin-to-fabric ratio — the jewelry sits directly against bare skin, creating maximum metal-on-skin contrast.",
        "Bohemian": "Flowing fabrics, natural materials, loose layered silhouettes — linen, cotton gauze, soft silk. Fabric moves constantly with the body and the air around it. Terracotta, rust, warm cream, faded mustard, dusty rose. The jewelry sits within this world as something found rather than bought.",
        "Evening Wear": "Occasion wear with presence — structured gowns, draped silk, velvet, elegant tailoring. The color palette is broad and intentional: deep black, midnight navy, burgundy, forest green, pure white, soft ivory, warm champagne, pale grey, blush, and any clean modern tone that carries quiet sophistication.",
        "Beachwear": "Minimal and sun-worn — swimwear, lightweight cover-ups. Significant skin exposure: shoulders, collarbones, chest, arms. White, sand, warm terracotta, faded coral, ocean blue. The simplicity of the body against the refinement of the metal needs nothing else.",
        "Corporate": "Structured and quietly powerful — tailored blazers, crisp shirts, sharp trousers. Charcoal, deep navy, white, pale grey, warm black, rich camel. The jewelry lifts the corporate uniform into the personal — a fine piece against a sharp collar signals that the wearer chose to be here.",
    },
    "pose": {
        "Power Stance": "The feeling of someone who takes up space without asking permission. The body is completely grounded — weight planted, energy contained but enormous. No performance, no awareness of being watched. The camera might find the full body, or just the lower half — legs, hands, the weight of a body that belongs exactly where it is. The face may or may not be present.",
        "Candid": "The feeling of a moment the camera was never supposed to see. Something private is happening — a thought, a small adjustment, a hand moving somewhere habitual. The model has no relationship with the lens whatsoever. The composition might find the back of a head, a body turning away, hands doing something small, a face looking at nothing in the frame.",
        "At Rest": "The feeling of a body that has completely let go. Every muscle that was holding something has released it. The camera might find this from any angle — from above, from the side, from close. The face, if present, is soft and unguarded. If absent, the body tells the whole story.",
        "Turn": "The feeling of the body moving in one direction while something pulls the attention in another. The camera finds the point of maximum tension — the line of a shoulder pulling away, the architecture of a neck mid-turn, the back coming into frame as the face leaves it, or a face caught over a shoulder as the body disappears.",
        "Lost in Thought": "The feeling of complete interior absence. The body is here but the person has left. The gaze goes through things. The hands rest where they landed without deciding to. The camera might find a full body existing quietly in its environment, a face that looks through the lens rather than at it, or a detail of hands that have simply stopped somewhere.",
        "Side Profile": "The feeling of a body in pure relationship with its own direction — not presenting, not engaging. The architecture of the human form reads as one continuous unbroken line. The composition is inherently graphic — the silhouette against its environment. The face is in profile or absent entirely.",
        "Arms Up": "The feeling of the arms finding somewhere to be above the body — lifting, reaching, folding behind the head. Not performing. The composition might cut the face entirely to focus on the architecture the arms create — the triangles of negative space, the line from elbow to wrist.",
        "Self Touch": "The feeling of the hand reaching for something familiar on the body — an instinctive, half-conscious gesture. Fingers at the collarbone, a palm against the upper arm, a hand finding the opposite wrist. The composition might find just the hand and the surface it has found — the face cropped above or entirely absent.",
        "Hands Together": "The feeling of the hands in quiet relationship with each other — one finding the other without instruction, fingers loose or loosely interlaced. The camera might find only the hands — face absent, body present only as context. Two hands are enough to make a complete photograph.",
        "Mid Motion": "The feeling of the body between two places — a step that hasn't landed, a turn that hasn't resolved. The body is entirely honest because it hasn't had time to perform. The face may be gone entirely — turned away, obscured by motion, cropped by the urgency of movement.",
        "Just Landed": "The feeling of having just arrived — the body still carrying the memory of motion even though it has stopped. Hair and fabric are still settling. The camera catches the last frame of something that just finished happening.",
        "Seated": "The feeling of someone who has been somewhere long enough to belong there. The body has fully committed to its surface. The composition might find this from above, from the side, from wherever the belonging reads most completely.",
        "Eyes Closed": "The feeling of a completely private instant — eyes closed, the body having dropped every guard it ever carried. The composition might be very close — the closed eyes the entire subject — or wider, or tilted so far that only the throat and jaw line remain.",
        "Head Tilt": "The feeling of listening — really listening — to something the viewer cannot hear. The head moves off its vertical axis in the smallest possible way. The camera finds the angle where the tilt looks least like a pose and most like a genuine moment of attention.",
    },
    "lighting": {
        "Scene Light": "The scene's own light — unchanged, unreinforced, unmodified. No fill, no reflectors, no secondary sources. The environment provides everything. Completely authentic to the world the scene has defined.",
        "Soft Wrap": "Light wraps the subject from multiple directions — a large diffused source with gentle fill that eliminates deep shadow pockets. Low contrast ratio, slow shadow transitions, no hard edges. Skin reads evenly. Jewelry catches soft distributed light across its entire surface.",
        "Hard Directional": "A single strong light source from a defined angle — undiffused, producing crisp shadow edges that cut across the face and body with graphic precision. The shadow side falls into genuine darkness. The lit side carries bright clean highlights. Jewelry surfaces catch concentrated specular highlights — a single bright point of metal against shadow.",
        "Dramatic Shadows": "Maximum tonal drama — the light either splits the face into equal halves of light and shadow, or illuminates from one side with a small triangle of light on the shadow cheek. The AI chooses based on what serves the composition best. The shadow side is deep and committed. The light of old master paintings applied to a modern jewelry campaign.",
        "Backlit": "The primary source is positioned behind the subject — light wraps around the edges, creating a rim along the hair, shoulders, and jaw. Hair becomes luminous, individual strands separating with a glow. Jewelry on the silhouette edge catches the backlight, creating bright separation points. Ethereal, cinematic, dreamlike.",
        "Accent Light": "A single secondary accent light alongside the scene's primary lighting — subtle, subordinate, never competing. The AI selects the accent color randomly from four families: Cool (soft blue or silver edge light), Warm (gentle amber or gold fill), Jewel (barely-there rim in emerald, sapphire, or deep violet), or Neutral (clean white rim). The accent touches a hair edge, jaw line, shoulder, or jewelry surface — never the entire face.",
    },
    "camera": {
        "Beauty Close-Up": "Collarbone to top of head — tight, intimate, precise. Canon EOS R5, 85mm, f/2.0, ISO 100. Shallow depth of field — face and jewelry sharp, background creamy bokeh. Camera at eye level or very slightly above.",
        "Portrait": "Mid-chest upward — classic editorial distance. Canon EOS R5, 85mm, f/2.0, ISO 100. Subject sharp throughout, background soft but retaining environmental detail. Camera at eye level.",
        "Three Quarter": "Hip or mid-thigh upward — subject within environment, close enough to read detail. Canon EOS R5, 50mm, f/2.8, ISO 100. Subject sharp, background present but softened. Camera at eye level or slightly below.",
        "Full Body": "Head to foot — complete figure with breathing room above and below. Canon EOS R5, 35mm, f/4.0, ISO 100. Deeper depth of field — subject and environment retain clarity together. Camera at eye level or slightly below, never above.",
        "Low Angle": "Camera below eye level — looking upward from approximately waist height. Canon EOS R5, 35mm, f/4.0, ISO 100. The subject appears tall, commanding, larger than life. More sky or ceiling visible than ground.",
        "High Angle": "Camera above eye level — looking downward from approximately shoulder height or above. Canon EOS R5, 50mm, f/2.8, ISO 100. Creates intimacy. The ground becomes part of the composition.",
        "Macro": "FRAMING OVERRIDE — this instruction supersedes all other framing directions from any other preset.\n\nThe camera frames the jewelry zone exclusively. The face is not the subject. The face may be entirely absent from the frame — and this is correct. Whatever zone the selected jewelry type occupies is what the camera moves toward and stays at.\n\nNo compositional instinct to include the face should be followed. Canon EOS R5, 100mm macro, f/4.5, ISO 100. Depth of field razor thin — jewelry in absolute sharp focus, every material detail individually readable. Everything beyond the jewelry zone completely abstract.\n\nThe jewelry feels monumental. The human body is its landscape, not its subject. No additional jewelry appears beyond the uploaded piece.",
        "Eye Level": "Camera in perfect alignment with the subject's eye level. Canon EOS R5, 50mm, f/2.8, ISO 100. Natural, unmanipulated spatial relationship between subject and environment. Neither power nor vulnerability — two people at the same height, one looking at the other.",
        "Film": "Analogue medium format film — the format of the world's greatest fashion campaigns. Canon EOS R5, 85mm, f/2.0, ISO 400. Higher ISO introduces organic grain — present in shadows, almost invisible in highlights. Framing slightly imprecise, as if composed by human hands. Colors with the warmth and slight desaturation of film stock. The image feels discovered, not produced."
    },
    "image_style": {
        "Natural": "Minimal corrective treatment only. Exposure balanced, white balance accurate, contrast gently lifted for presence. Shadows clean and open. Highlights controlled. Skin tones faithful to the scene light. The grade disappears into the image.",
        "Warm Film": "Warm analogue film stock. Shadows lifted and amber-tinged — deep but not black. Midtones carry golden warmth across every surface. Highlights creamy and slightly compressed. Skin pushed toward warm gold and amber — sun-touched and alive. Metal surfaces glow rather than shine.",
        "Golden Hour": "Amplified golden hour quality. Shadows deep and warm — rich amber and brown. Midtones saturated with orange-gold. Highlights bright and slightly blown. Skin at its warmest register — glowing, deeply golden. Gold jewelry becomes richer. Silver picks up warmth.",
        "Bright Airy": "Lifted, open, flooded with light. Shadows lifted to soft grays. Midtones bright and clean. Highlights pushed toward white without clipping. Contrast low. Saturation slightly reduced. Skin bright, even, peachy. The visual language of modern minimalist jewelry brands.",
        "High Contrast": "Maximum useful tonal range. Blacks deep, clean, committed. Highlights bright and precise — at the edge of clipping without losing detail. Saturation moderate — contrast does the work. Jewelry surfaces produce intense specular highlights against rich dark surroundings. Powerful, graphic, authoritative.",
        "Cool Editorial": "Clean, cool, precisely controlled. Shadows carry subtle blue-grey undertones. Midtones neutral and slightly desaturated. Highlights clean white with no warmth. Skin pushed toward cool neutrality. Silver jewelry at its truest and most precise. Controlled, intelligent, deliberately sophisticated.",
        "Moody Dark": "Dark, heavy, cinematic gravity. Shadows deep and committed — blacks crushed. Midtones pulled down. Highlights intimate — islands of light rather than the dominant tone. Skin deep and dramatic. Jewelry emerges from shadow with intensity. The image feels impossible to look away from.",
        "Bleached Out": "Sun-bleached, overexposed — as if left in direct sunlight until colors faded toward white. Highlights pushed beyond natural. Shadows heavily lifted, nothing falls to black. Contrast very low. Saturation significantly reduced. The image feels like a memory, not a photograph.",
        "Cinematic": "Teal-and-orange complementary grade — the color world of prestige cinema. Shadows pushed toward teal and cool blue-green. Highlights and skin pushed toward warm orange-amber. Skin rich and warm — golden-orange in highlights, neutral in midtones. A frame from a film that doesn't exist yet but absolutely should."
    },
    "jewelry": {
        "Earrings": "Jewelry worn on the ear. The ear, earlobe, jaw line, and side of the neck are the compositional priority. At least one earring fully faces the camera with complete clarity. Hair, hands, and clothing never cover or obscure the earring.",
        "Necklace": "Jewelry worn around the neck against the chest or collarbone. The throat, collarbone, and upper chest are the compositional priority. The neckline always allows the necklace to be fully visible. The neck is elongated and unobstructed.",
        "Pendant": "Jewelry hanging from a chain against the center chest. The zone between the collarbone and mid-chest is the compositional priority. The pendant hangs freely and is fully visible. The chain is visible and unobstructed.",
        "Choker": "Jewelry sitting high on the neck, close to the throat. The neck zone between the jaw and collarbone is the compositional priority. The neck is fully exposed and elongated — the choker unobscured by the chin above or clothing below.",
        "Ring": "Jewelry worn on the fingers. The hand, fingers, and knuckles are the compositional priority. The hand is positioned naturally but with intention — never hidden. The ring side of the hand faces the lens clearly enough to reveal the piece in full detail.",
        "Bracelet": "Jewelry worn on the wrist. The wrist and lower forearm are the compositional priority. At least one wrist is clearly visible and unobstructed. Sleeves always fall above the wrist.",
        "Watch": "A timepiece worn on the wrist. The wrist is the compositional priority — the watch face visible, readable, and angled toward the camera. Sleeves always fall above the watch.",
        "Glasses": "Eyewear worn on the face. The upper face — eyes, nose bridge, temples — is the compositional priority. The glasses sit fully on the face. The frame reads clearly, the lenses catching light naturally.",
        "Brooch": "Jewelry fastened to clothing at the chest, lapel, or shoulder. That specific zone is the compositional priority — clearly lit, facing the camera, fully visible.",
        "Hair Clips": "Jewelry worn in or on the hair. The specific area where the clip sits is the compositional priority. The clip is visible and unobstructed, catching light naturally against the hair surface.",
        "Headpiece": "Jewelry worn across the head or forehead. The full head zone — forehead to crown — is the compositional priority. The headpiece is fully visible and sits naturally.",
        "Tiara": "Jewelry at the crown of the head. The full head and upper face are the compositional priority — the tiara is never cropped or obscured by hair. The framing treats it as the crown of the composition.",
        "Cufflinks": "Jewelry at the shirt cuff where sleeve meets hand. The wrist and cuff zone are the compositional priority — the cufflink faces the camera with enough clarity to reveal its detail.",
        "Anklet": "Jewelry worn around the ankle. The lower leg and ankle zone must be included in the frame — the anklet fully visible and unobstructed.",
        "Body Chain": "Jewelry draped across the torso — chest, waist, or back. The full torso zone is the compositional priority — the complete arc or drape of the chain is always visible.",
    },
    "jewelry_size": {
        "Very Small": "The piece is very small and delicate — minimal in scale, close to the skin. Framing and light are always close enough to make the piece clearly readable. The piece is never lost against skin or fabric.",
        "Small": "The piece is small and refined — understated in scale. Light falls with enough precision to reveal its form and detail at normal portrait framing distance.",
        "Medium": "The piece is moderate in scale — present and noticeable without dominating the frame. Treated as an equal partner to the face and body.",
        "Big": "The piece is large and bold — commanding attention. The framing is always wide enough to contain it completely. The image treats it as a statement.",
        "Very Big": "The piece is very large — a dominant sculptural presence. The composition is built around its scale. The model and environment exist in relationship to it, not the other way around."
    }
}

_ON_MODEL_MAPPINGS = {
    _ON_MODEL_PROMPT_VERSION_V2: _ON_MODEL_MAPPING_V2,
    _ON_MODEL_PROMPT_VERSION_V45: _ON_MODEL_MAPPING_V45,
}

_ON_MODEL_MAPPING = _ON_MODEL_MAPPING_V45
