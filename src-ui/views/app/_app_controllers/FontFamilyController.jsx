import { useEffect } from "react";
import { useAppearance } from "@logics_configs";

export const FontFamilyController = () => {
    const { currentSelectedFontFamily } = useAppearance();
    useEffect(() => {
        const name = currentSelectedFontFamily.data;
        const style = document.documentElement.style;
        // The name goes into font-family as one CSS string, as Quick Chat does.
        // Unquoted, a name such as "M PLUS 1p" or "@MS Gothic" is not a valid
        // family list, the whole declaration is dropped and the page falls
        // back to the browser default serif font.
        if (typeof name === "string" && name !== "") style.setProperty("--font_family", JSON.stringify(name));
        else style.removeProperty("--font_family");
    }, [currentSelectedFontFamily.data]);

    return null;
};
