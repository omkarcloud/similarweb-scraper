"""Marshmallow request schemas for every /similarweb/* route.

Generic fields live in the shared top-level schema_fields.py; this module
adds the Similarweb resolvers (refs.py). Every schema's load() output is the
kwargs dict its endpoint function takes.

ONE param per input (tripadvisor QueryOrLinkField convention, never a
sibling `url`/`domain` pair): `website` / `company` take a domain OR any link
on it OR a similarweb.com / similarsites.com link; `app` a Play package / App
Store id OR a store / similarweb.com app link; `technology` a slug / name OR
its similarweb.com link; `country` an ISO code, English name or 'worldwide';
`category` a category (optionally '/subcategory') by id, name or top-list
link; `marketplace` an Amazon domain, country or product link.
"""
from marshmallow import ValidationError, fields, validate

from schema_fields import BaseSchema, ChoiceField, DateField, QueryField, RefField, StrippedString
from similarweb import refs

MAX_COMPARE = 10


# ---- resolver fields ----------------------------------------------------------------------

class WebsiteField(RefField):
    resolver = staticmethod(refs.resolve_website)


class AppField(RefField):
    resolver = staticmethod(refs.resolve_app)


class TechnologyField(RefField):
    resolver = staticmethod(refs.resolve_technology)


class CountryField(RefField):
    """ISO code / name / 'worldwide' (-> None). Optional."""
    resolver = staticmethod(refs.resolve_country)

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)


class WebsiteCategoryField(RefField):
    resolver = staticmethod(refs.resolve_website_category)

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)


class AppCategoryField(WebsiteCategoryField):
    resolver = staticmethod(refs.resolve_app_category)


class MarketplaceField(RefField):
    resolver = staticmethod(refs.resolve_amazon_marketplace)


class WebsiteListField(fields.Field):
    """'github.com, gitlab.com,https://bitbucket.org/x' -> ['github.com', 'gitlab.com',
    'bitbucket.org'] (resolved, deduped, 1..MAX_COMPARE)."""

    def _deserialize(self, value, attr, data, **kwargs):
        out = []
        for item in str(value or "").split(","):
            item = item.strip()
            if not item:
                continue
            try:
                domain = refs.resolve_website(item)
            except ValueError as e:
                raise ValidationError(f"'{item}': {e}")
            if domain not in out:
                out.append(domain)
        if not out:
            raise ValidationError("Must list at least one website (comma-separated domains or links).")
        if len(out) > MAX_COMPARE:
            raise ValidationError(f"At most {MAX_COMPARE} websites.")
        return out


# ---- websites ------------------------------------------------------------------------------

class WebsiteSchema(BaseSchema):
    website = WebsiteField()


class CompareSchema(BaseSchema):
    websites = WebsiteListField(required=True)


class CompanySchema(BaseSchema):
    company = WebsiteField()


# ---- apps -----------------------------------------------------------------------------------

class AppSchema(BaseSchema):
    app = AppField()
    country = CountryField()


class TrendingAppsSchema(BaseSchema):
    store = ChoiceField(["google", "apple"], load_default="google")
    country = CountryField()
    category = AppCategoryField()
    chart_type = ChoiceField(["free", "paid", "grossing"], load_default="free")
    device = ChoiceField(["iphone", "ipad"])


class TopAppsSchema(TrendingAppsSchema):
    sort = ChoiceField(["store_rank", "usage_rank"], load_default="store_rank")
    date = DateField(bound="past")


# ---- rankings / market share ------------------------------------------------------------------

class TopWebsitesSchema(BaseSchema):
    country = CountryField()
    category = WebsiteCategoryField()


class BrowsersSchema(BaseSchema):
    country = CountryField()
    platform = ChoiceField(["desktop", "mobile", "tablet"])


class DevicesSchema(BaseSchema):
    country = CountryField()


# ---- search -----------------------------------------------------------------------------------

class SearchSchema(BaseSchema):
    query = QueryField(max_length=100, validate=validate.Length(min=2, max=100))


class AutocompleteSchema(SearchSchema):
    type = ChoiceField(["all", "websites", "apps"], load_default="all")


# ---- technologies / Amazon ------------------------------------------------------------------------

class TechnologySchema(BaseSchema):
    technology = TechnologyField()


class AmazonCategoriesSchema(BaseSchema):
    marketplace = MarketplaceField(required=False, load_default="amazon.com")


class AmazonTopBrandsSchema(AmazonCategoriesSchema):
    category = StrippedString(required=False, load_default=None, validate=validate.Length(max=200))


class EmptySchema(BaseSchema):
    pass
